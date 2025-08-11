// --- START OF FILE qa-automation-lti.js (Definitive V3) ---

const path = require('path')
const express = require('express')
require('dotenv').config()

// Require Provider 
const lti = require('ltijs').Provider

// Setup provider
lti.setup(process.env.LTI_KEY || 'QA_AUTOMATION_KEY_2024',
  { // Database configuration
    url: process.env.MONGODB_URL || 'mongodb://localhost:27017/qa-automation-lti',
    connection: { 
      // Add MongoDB credentials here when needed
    }
  },
  { // Options
    appRoute: '/qa-tools', 
    loginRoute: '/login',
    keysetRoute: '/keys',
    cookies: {
      secure: false, // Set to true for production with HTTPS
      sameSite: 'None' // Required for Canvas iframe integration
    },
    devMode: true, // Set to false in production
    tokenMaxAge: 300, // Increase token max age to 5 minutes (default is 10 seconds)
    staticPath: path.join(__dirname, 'public')
  }
)

// Whitelist the execute endpoints
lti.whitelist('/execute')
lti.whitelist('/execute-approved')

// --- BACKEND LOGIC ---

// Enhanced /execute endpoint with robust error handling
lti.app.post('/execute', async (req, res) => {
  const { taskId, courseId, userId } = req.body
  
  try {
    console.log(`Analyzing task: ${taskId} for course: ${courseId}`)
    
    if (!taskId || !courseId) {
      throw new Error('Task ID and Course ID are required.');
    }
    
    const analysisResult = await analyzeTask(taskId, courseId, userId)
    
    res.json({ 
      success: true, 
      phase: 3,
      mode: 'preview_first',
      taskId,
      result: analysisResult 
    })
  } catch (error) {
    console.error('Analysis error:', error)
    res.status(500).json({ 
      success: false, 
      error: error.message,
      phase: 3,
      debug: {
        taskId,
        courseId,
        timestamp: new Date().toISOString(),
        errorType: error.constructor.name
      }
    })
  }
})

// V3: analyzeTask function that calls the correct Python script
async function analyzeTask(taskId, courseId, userId) {
  const { spawn } = require('child_process');
  const path = require('path');
  const fs = require('fs');
  
  return new Promise((resolve, reject) => {
    const scriptName = QA_TASKS[taskId]?.script;
    if (!scriptName) {
      return reject(new Error(`Unknown or misconfigured task: ${taskId}`));
    }
    
    const scriptPath = path.join(__dirname, 'scripts', scriptName);
    const canvasUrl = process.env.CANVAS_URL || 'aculeo.test.instructure.com';
    const apiToken = process.env.CANVAS_API_TOKEN || '';
        
    if (!apiToken) {
      return reject(new Error('Canvas API token not configured in environment.'));
    }
    if (!fs.existsSync(scriptPath)) {
      return reject(new Error(`Required script not found at: ${scriptPath}`));
    }
        
    const args = [
      scriptPath,
      '--canvas-url', canvasUrl.replace(/^https?:\/\//, ''), // Ensure no scheme is passed
      '--api-token', apiToken,
      '--course-id', courseId,
      '--analyze-only'
    ];
        
    console.log('V3 Analysis with args:', args);
        
    const timeoutMs = 300000; // 5 minutes
    const timeout = setTimeout(() => {
      python.kill('SIGTERM');
      reject(new Error('Analysis timed out after 5 minutes. This may indicate a large course or network issue.'));
    }, timeoutMs);
        
    const python = spawn('python3', args, { cwd: __dirname });
        
    let output = '';
    let error = '';
        
    python.stdout.on('data', (data) => output += data.toString());
    python.stderr.on('data', (data) => error += data.toString());
        
    python.on('close', (code) => {
      clearTimeout(timeout);
          
      if (code === 0) {
        try {
          const jsonMatch = output.match(/ENHANCED_ANALYSIS_JSON:\s*(\{[\s\S]*\})/);
          if (jsonMatch && jsonMatch[1]) {
            return resolve(JSON.parse(jsonMatch[1]));
          }
          reject(new Error('Analysis completed, but no recognizable results were found in the output. Raw output: ' + output));
        } catch (parseError) {
          console.error('Failed to parse script JSON output:', parseError);
          reject(new Error('Analysis completed but result processing failed.'));
        }
      } else {
        let errorMessage = `Analysis script failed with exit code ${code}.`;
        if (error.includes('ModuleNotFoundError')) {
          const missingModule = error.match(/No module named '([^']+)'/);
          errorMessage = missingModule ? `Missing Python package: ${missingModule[1]}. Please run: pip install ${missingModule[1]}` : 'Missing Python dependencies.';
        } else if (error.includes('401') || error.includes('Unauthorized')) {
          errorMessage = 'Canvas API authentication failed (401). Please check your API token.';
        } else if (error.includes('403') || error.includes('Forbidden')) {
          errorMessage = 'Canvas API access forbidden (403). Please check your API token permissions.';
        } else if (error.includes('404')) {
          errorMessage = 'Course not found or API endpoint invalid (404). Please check the course ID.';
        } else if (error) {
          errorMessage = `The script encountered an error: ${error.substring(0, 300)}...`;
        }
        reject(new Error(errorMessage));
      }
    });
        
    python.on('error', (spawnError) => {
      clearTimeout(timeout);
      console.error('Failed to start Python process:', spawnError);
      if (spawnError.code === 'ENOENT') {
        reject(new Error('Python 3 not found. Please ensure "python3" is in your system\'s PATH.'));
      } else {
        reject(new Error(`Failed to start the analysis process: ${spawnError.message}`));
      }
    });
  });
}

// V3: Endpoint for executing user-approved actions
lti.app.post('/execute-approved', async (req, res) => {
  const { taskId, courseId, userId, approvedActions } = req.body;
  
  try {
    console.log(`Executing ${approvedActions.length} approved actions for task: ${taskId}`);
    
    if (!taskId || !courseId || !Array.isArray(approvedActions)) {
      throw new Error('Task ID, Course ID, and a valid actions array are required.');
    }
    
    if (approvedActions.length === 0) {
      return res.json({ success: true, message: 'No actions were selected for execution.' });
    }
    
    const result = await executeApprovedActions(taskId, courseId, userId, approvedActions);
    
    res.json({ success: true, phase: 3, mode: 'execute_approved', taskId, result: result });
  } catch (error) {
    console.error('Execution error:', error);
    res.status(500).json({ success: false, error: error.message });
  }
});

// V3: executeApprovedActions now calls python script with `--execute-from-json`
async function executeApprovedActions(taskId, courseId, userId, approvedActions) {
  const { spawn } = require('child_process');
  const path = require('path');
  const fs = require('fs');

  return new Promise((resolve, reject) => {
    const scriptName = QA_TASKS[taskId]?.script;
    if (!scriptName) return reject(new Error(`Misconfigured task: ${taskId}`));

    const scriptPath = path.join(__dirname, 'scripts', scriptName);
    const canvasUrl = process.env.CANVAS_URL || 'aculeo.test.instructure.com';
    const apiToken = process.env.CANVAS_API_TOKEN || '';

    if (!apiToken) return reject(new Error('Canvas API token not configured.'));

    const tempDir = path.join(__dirname, 'temp');
    if (!fs.existsSync(tempDir)) fs.mkdirSync(tempDir, { recursive: true });
    
    const actionsFile = path.join(tempDir, `approved_actions_${courseId}_${Date.now()}.json`);
    fs.writeFileSync(actionsFile, JSON.stringify(approvedActions, null, 2));

    const args = [
      scriptPath,
      '--canvas-url', canvasUrl.replace(/^https?:\/\//, ''),
      '--api-token', apiToken,
      '--course-id', courseId,
      '--execute-from-json', actionsFile // Use the correct V3 argument
    ];

    console.log('V3 Executing approved actions with args:', args);
    const python = spawn('python3', args);

    let output = '';
    let error = '';

    python.stdout.on('data', (data) => output += data.toString());
    python.stderr.on('data', (data) => error += data.toString());

    python.on('close', (code) => {
      fs.unlinkSync(actionsFile); // Cleanup

      if (code === 0) {
        try {
          const jsonMatch = output.match(/EXECUTION_RESULTS_JSON:\s*(\{[\s\S]*\})/);
          if (jsonMatch && jsonMatch[1]) {
            const parsedResult = JSON.parse(jsonMatch[1]);
            console.log('✅ Execution results parsed successfully:', parsedResult);
            resolve(parsedResult);
          } else {
            console.log('⚠️ No EXECUTION_RESULTS_JSON found in output. Raw output:', output);
            resolve({ 
              summary: { successful: 0, failed: 0}, 
              message: "Execution ran but did not return structured results.",
              raw_output: output.substring(0, 500) // Include first 500 chars for debugging
            });
          }
        } catch (e) {
          console.error('❌ Failed to parse execution results:', e);
          reject(new Error(`Execution completed, but failed to parse results: ${e.message}`));
        }
      } else {
        console.error('❌ Execution script failed with code:', code);
        console.error('Error output:', error);
        reject(new Error(`Execution script failed: ${error || 'Unknown error'}`));
      }
    });
  });
}

// --- LTI & FRONTEND LOGIC ---

// QA Task Definitions - Central source of truth for all tasks
const QA_TASKS = {
  'find-duplicate-pages': {
    name: 'Find and Remove Duplicate Pages',
    description: 'Scans for duplicate pages, prioritizing safety by checking for inbound links before recommending actions.',
    category: 'Content Management',
    script: 'duplicate_page_cleaner.py'
  },
  'validate-assignment-settings': {
    name: 'Validate Assignment Settings',
    description: 'Checks assignments for common QA issues like incorrect points, grading types, and confusing dates.',
    category: 'Assessment',
    script: 'assignment_settings_validator.py'
  },
  'title-alignment-checker': {
    name: 'Title Alignment Checker',
    description: 'Analyzes course modules for consistency between syllabus schedule and module titles, enforcing stylistic rules and validating welcome messages.',
    category: 'Content Management',
    script: 'title_alignment_checker.py'
  },
  'assessment-date-updater': {
    name: 'Assessment Date Updater',
    description: 'Replaces hard-coded dates in assessment reminder wells with week-based deadlines for consistency.',
    category: 'Content Management',
    script: 'assessment_date_updater.py'
  },
  'table-caption-checker': {
    name: 'Table Caption Checker',
    description: 'Checks table captions for compliance with ACU Online Design Library standards, ensuring proper styling and accessibility.',
    category: 'Media',
    script: 'table_caption_checker.py'
  },
  'remove-empty-groups-modules': {
    name: 'Remove Empty Groups & Modules',
    description: 'Identifies empty assignment groups and modules; preview safe deletions and execute only approved items.',
    category: 'Cleanup',
    script: 'empty_groups_modules_cleaner.py'
  },
  'rubric-cleanup': {
    name: 'Rubric Cleanup',
    description: 'Identifies unnecessary or unused rubrics and stages safe deletions for approval.',
    category: 'Assessment',
    script: 'rubric_cleanup_analyzer.py'
  },
  'syllabus-acuo-attribution-remover': {
    name: 'Remove Syllabus ACUO Attribution',
    description: 'Finds and safely removes "(ACU Online, YYYY)" attributions from the course syllabus with preview and approval.',
    category: 'Syllabus',
    script: 'syllabus_acuo_attribution_remover.py'
  }
}

// Main LTI launch handler
lti.onConnect(async (token, req, res) => {
  const realUserName = await getRealUserName(token);
  token.realUserName = realUserName;
  const html = generateEnhancedQADashboard(token)
  return res.send(html)
})

// Helper functions (getRealCourseId, getUserRole, getRealUserName) remain the same

function generateEnhancedQADashboard(token) {
  const taskCategories = groupTasksByCategory()
  
  return `
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Canvas QA Automation Suite</title>
    <style>
        :root {
            --acu-deep-purple: #4A1A4A; --acu-purple: #6B2C6B; --acu-red: #D2492A;
            --acu-red-dark: #B8391F; --acu-gold: #F4B942; --acu-gold-dark: #E6A830;
            --acu-cream: #F9F4F1; --acu-cream-dark: #F4ECE6;
            --acu-success: #F4B942; --canvas-border: #c7cdd1; --neutral-grey: #6c757d;
        }
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; margin: 0; padding: 20px; background: var(--acu-cream); color: var(--acu-purple); }
        .header { background: #fff; padding: 24px; border-radius: 8px; margin-bottom: 24px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); border-left: 4px solid var(--acu-deep-purple); }
        .header h1 { margin: 0 0 8px 0; font-size: 24px; }
        .task-category { background: #fff; margin-bottom: 24px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }
        .category-header { background: linear-gradient(135deg, var(--acu-deep-purple) 0%, var(--acu-purple) 100%); color: white; padding: 16px 24px; font-weight: 600; }
        .task-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 20px; padding: 24px; }
        .task-card { border: 1px solid var(--canvas-border); border-radius: 8px; padding: 20px; cursor: pointer; transition: all 0.2s ease; background: #fff; }
        .task-card:hover { border-color: var(--acu-deep-purple); transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.1); }
        .task-name { font-weight: 600; font-size: 16px; } .task-description { font-size: 14px; color: #555; margin: 8px 0 0 0; }
        .progress-overlay, .analysis-preview { position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.6); display: flex; align-items: center; justify-content: center; z-index: 1000; opacity: 0; visibility: hidden; transition: opacity 0.3s ease; }
        .progress-overlay.active, .analysis-preview.active { opacity: 1; visibility: visible; }
        .progress-card, .preview-card { background: #fff; padding: 32px; border-radius: 12px; box-shadow: 0 10px 40px rgba(0,0,0,0.2); text-align: center; max-width: 500px; width: 90%; }
        .progress-spinner { width: 48px; height: 48px; border: 4px solid #f0f0f0; border-top: 4px solid var(--acu-red); border-radius: 50%; animation: spin 1s linear infinite; margin: 0 auto 20px; }
        @keyframes spin { 100% { transform: rotate(360deg); } }
        .preview-card { text-align: left; max-height: 80vh; display: flex; flex-direction: column; }
        .preview-header { padding-bottom: 16px; margin-bottom: 16px; border-bottom: 1px solid var(--canvas-border); display: flex; justify-content: space-between; align-items: center; }
        .preview-content { overflow-y: auto; }
        .preview-actions { padding-top: 24px; text-align: right; border-top: 1px solid var(--canvas-border); margin-top: 24px; }
                 .btn-primary, .btn-secondary { padding: 12px 24px; border-radius: 6px; border: none; font-weight: 500; cursor: pointer; transition: all 0.2s ease; }
         .btn-primary { background: var(--acu-red); color: white; } .btn-primary:hover { background: var(--acu-red-dark); }
         .btn-secondary { background: var(--acu-gold); color: var(--acu-deep-purple); } .btn-secondary:hover { background: var(--acu-gold-dark); }
        .results-container { margin-top: 24px; background: #fff; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); display: none; }
        .results-header { background: linear-gradient(135deg, var(--acu-deep-purple) 0%, var(--acu-purple) 100%); color: white; padding: 20px 24px; font-weight: 600; }
        .results-content { padding: 24px; }
        .result-section { margin-bottom: 24px; padding: 16px; border-radius: 8px; border-width: 1px; border-style: solid; }
        .result-section h4 { margin-top: 0; display: flex; align-items: center; }
        .action-item { display: flex; align-items: center; padding: 8px; border-radius: 4px; margin-bottom: 8px; background: #f8f9fa; }
        .action-item.clickable { transition: all 0.2s ease; border: 1px solid transparent; }
        .action-item.clickable:hover { background: #e9ecef; border-color: var(--acu-deep-purple); transform: translateY(-1px); box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .action-item input[type=checkbox] { margin-right: 12px; transform: scale(1.2); }
        .action-item label { flex-grow: 1; }
        .action-content { flex-grow: 1; }
        .action-icon { margin-left: 12px; font-size: 18px; color: var(--acu-deep-purple); }
        .manual-steps { background: var(--acu-cream-dark); padding: 16px; border-radius: 6px; margin: 16px 0; }
        .manual-steps ol { margin: 8px 0; padding-left: 20px; }
        .manual-steps li { margin-bottom: 8px; }
        .examples { background: #f8f9fa; padding: 16px; border-radius: 6px; margin: 16px 0; }
        .example-item { margin-bottom: 8px; }
        .example-item code { background: #e9ecef; padding: 2px 4px; border-radius: 3px; font-family: monospace; }
        /* NEW: Severity styles for consistent UI */
                 .result-section.severity-high { border-color: var(--acu-red); }
         .result-section.severity-medium { border-color: var(--acu-gold); }
         .result-section.severity-low { border-color: var(--neutral-grey); }
         .result-section.severity-safe { border-color: var(--acu-success); }
        .severity-badge { font-size: 0.75em; padding: 2px 8px; border-radius: 10px; color: white; margin-left: 10px; text-transform: uppercase; }
        .severity-badge.high { background-color: var(--acu-red); }
        .severity-badge.medium { background-color: var(--acu-gold); }
        .severity-badge.low { background-color: var(--neutral-grey); }
        /* NEW: Execution results specific styles */
        .execution-summary { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; padding: 16px; border-radius: 8px; border: 1px solid var(--canvas-border); background: #f9f9f9; }
        .execution-stats { display: flex; align-items: center; }
        .stat-card { padding: 12px 20px; border-radius: 6px; color: white; font-weight: bold; }
                 .stat-card.success { background: var(--acu-success); color: var(--acu-deep-purple); }
         .stat-card.mixed { background: linear-gradient(to right, var(--acu-red), var(--acu-gold)); }
         .failure-note { font-size: 0.9em; color: var(--acu-red); margin-top: 4px; }
         .timestamp { font-size: 0.8em; color: var(--acu-purple); margin-top: 4px; }
         .execution-details { margin-top: 12px; }
         .execution-item { display: flex; align-items: center; margin-bottom: 8px; }
         .execution-item .execution-icon { font-size: 1.2em; margin-right: 10px; }
         .execution-item.success .execution-icon { color: var(--acu-success); }
         .execution-item.failure .execution-icon { color: var(--acu-red); }
         .execution-item .execution-content { flex-grow: 1; }
         .execution-item .fix-detail { font-size: 0.8em; color: var(--acu-purple); }
         .execution-item .original-issue { font-size: 0.8em; color: var(--neutral-grey); }
                 .execution-actions { margin-top: 24px; text-align: right; }
         .action-buttons { display: flex; gap: 10px; justify-content: flex-end; margin-bottom: 16px; }
                 .next-steps { margin-top: 24px; padding-top: 16px; border-top: 1px solid var(--canvas-border); }
         .next-steps h4 { margin-top: 0; margin-bottom: 12px; }
         .next-steps ul { list-style: none; padding: 0; margin: 0; }
         .next-steps li { margin-bottom: 8px; }
         .success-message { margin-top: 24px; padding: 16px; border-radius: 8px; background: var(--acu-cream-dark); border: 1px solid var(--acu-gold); color: var(--acu-deep-purple); }
         .success-message h4 { margin-top: 0; margin-bottom: 8px; color: var(--acu-purple); }
    </style>
            <script src="https://unpkg.com/xlsx@0.18.5/dist/xlsx.full.min.js"></script>
        <script>
            // QA_TASKS will be defined in the main script below
        </script>
</head>
<body>
    <div class="header">
        <h1>Canvas QA Automation Suite</h1>
        <p>Intelligent tools to streamline course quality assurance. Built with Human-Centered principles.</p>
        <div class="course-info">
            <strong>User:</strong> ${token.realUserName} | <strong>Course:</strong> ${token.platformContext?.context?.title} | <strong>Role:</strong> ${getUserRole(token)}
        </div>
    </div>

    ${Object.entries(taskCategories).map(([category, tasks]) => `
        <div class="task-category">
            <div class="category-header">${category}</div>
            <div class="task-grid">
                ${tasks.map(task => `
                    <div class="task-card" data-task-id="${task.id}" tabindex="0" role="button" aria-label="Analyze ${task.name}">
                        <div class="task-name">${task.name}</div>
                        <div class="task-description">${task.description}</div>
                    </div>
                `).join('')}
            </div>
        </div>
    `).join('')}

    <div class="analysis-preview" id="analysisPreview">
        <div class="preview-card">
            <div class="preview-header">
                <h2 id="previewTitle">Analysis Overview</h2>
                <button class="btn-secondary" style="padding: 4px 8px;" onclick="QAApp.closePreview()">×</button>
            </div>
            <div class="preview-content" id="previewContent"></div>
            <div class="preview-actions">
                <button class="btn-secondary" onclick="QAApp.closePreview()">Cancel</button>
                <button class="btn-primary" onclick="QAApp.proceedWithAnalysis()">Proceed</button>
            </div>
        </div>
    </div>
    
    <div class="progress-overlay" id="progressOverlay">
        <div class="progress-card">
            <div class="progress-spinner"></div>
            <h3 id="progressText">Initializing analysis...</h3>
            <p id="progressDetails">This may take a few moments.</p>
        </div>
    </div>

    <div class="results-container" id="resultsContainer">
        <div class="results-header"><h2 id="resultsTitle">Analysis Complete</h2></div>
        <div class="results-content" id="resultsContent"></div>
    </div>

            <script>
            // Make QA_TASKS available in the browser
            const QA_TASKS = {
                'find-duplicate-pages': {
                    name: 'Find and Remove Duplicate Pages',
                    description: 'Scans for duplicate pages, prioritizing safety by checking for inbound links before recommending actions.',
                    category: 'Content Management',
                    script: 'duplicate_page_cleaner.py'
                },
                'validate-assignment-settings': {
                    name: 'Validate Assignment Settings',
                    description: 'Checks assignments for common QA issues like incorrect points, grading types, and confusing dates.',
                    category: 'Assessment',
                    script: 'assignment_settings_validator.py'
                },
                'title-alignment-checker': {
                    name: 'Title Alignment Checker',
                    description: 'Analyzes course modules for consistency between syllabus schedule and module titles, enforcing stylistic rules and validating welcome messages.',
                    category: 'Content Management',
                    script: 'title_alignment_checker.py'
                },
                'assessment-date-updater': {
                    name: 'Assessment Date Updater',
                    description: 'Replaces hard-coded dates in assessment reminder wells with week-based deadlines for consistency.',
                    category: 'Content Management',
                    script: 'assessment_date_updater.py'
                },
                'table-caption-checker': {
                    name: 'Table Caption Checker',
                    description: 'Checks table captions for compliance with ACU Online Design Library standards, ensuring proper styling and accessibility.',
                    category: 'Media',
                    script: 'table_caption_checker.py'
                },
                'remove-empty-groups-modules': {
                    name: 'Remove Empty Groups & Modules',
                    description: 'Identifies empty assignment groups and modules; preview safe deletions and execute only approved items.',
                    category: 'Cleanup',
                    script: 'empty_groups_modules_cleaner.py'
                },
                'rubric-cleanup': {
                    name: 'Rubric Cleanup',
                    description: 'Identifies unnecessary or unused rubrics and stages safe deletions for approval.',
                    category: 'Assessment',
                    script: 'rubric_cleanup_analyzer.py'
                },
                'syllabus-acuo-attribution-remover': {
                    name: 'Remove Syllabus ACUO Attribution',
                    description: 'Finds and safely removes "(ACU Online, YYYY)" attributions from the course syllabus with preview and approval.',
                    category: 'Syllabus',
                    script: 'syllabus_acuo_attribution_remover.py'
                }
            };
            
            window.QAApp = (function() {
                let currentTaskId = null;
                let currentAnalysisResult = null;
                const courseId = '${getRealCourseId(token)}';
                const userId = '${token.sub || "unknown"}';
                const userName = '${token.realUserName}';



            function showProgress(text, details) {
                document.getElementById('progressText').textContent = text;
                document.getElementById('progressDetails').textContent = details;
                document.getElementById('progressOverlay').classList.add('active');
            }



            function hideProgress() {
                document.getElementById('progressOverlay').classList.remove('active');
            }


            
            // --- NEW: The results "router" ---
            function showResults(taskId, result) {
                currentAnalysisResult = result;
                const container = document.getElementById('resultsContainer');
                document.getElementById('resultsTitle').textContent = \`Results: \${QA_TASKS[taskId].name}\`;
                
                let contentHtml = '';
                if (taskId === 'find-duplicate-pages') {
                    contentHtml = generateDuplicateResultsHtml(result);
                } else if (taskId === 'validate-assignment-settings') {
                    contentHtml = generateAssignmentResultsHtml(result);
                } else if (taskId === 'assessment-date-updater') {
                    contentHtml = generateAssessmentDateResultsHtml(result);
                } else if (taskId === 'table-caption-checker') {
                    contentHtml = generateTableCaptionResultsHtml(result);
                } else if (taskId === 'remove-empty-groups-modules') {
                    contentHtml = generateEmptyGroupsModulesResultsHtml(result);
                } else if (taskId === 'rubric-cleanup') {
                    contentHtml = generateRubricCleanupResultsHtml(result);
                } else if (taskId === 'syllabus-acuo-attribution-remover') {
                    contentHtml = generateSyllabusAttributionResultsHtml(result);
                } else {
                    contentHtml = generateGenericResultsHtml(result); // Fallback
                }
                
                document.getElementById('resultsContent').innerHTML = contentHtml;
                container.style.display = 'block';
                container.scrollIntoView({ behavior: 'smooth' });
            }
            
            function showError(errorMsg) {
                const container = document.getElementById('resultsContainer');
                document.getElementById('resultsTitle').textContent = 'An Error Occurred';
                document.getElementById('resultsContent').innerHTML = \`
                    <div class="result-section" style="border-color: var(--acu-red); background: #fff5f5;">
                        <h4>Analysis Could Not Complete</h4>
                        <p>The system encountered an issue. Please see the details below.</p>
                        <pre style="background: #eee; padding: 10px; border-radius: 4px; white-space: pre-wrap; word-break: break-all;">\${errorMsg}</pre>
                        <button class="btn-primary" onclick="window.location.reload()">Try Again</button>
                    </div>\`;
                container.style.display = 'block';
                container.scrollIntoView({ behavior: 'smooth' });
            }

            // --- HTML RENDERERS ---

            function generateDuplicateResultsHtml(result) {
                const { safe_actions = [], requires_manual_review = [] } = result.findings || {};
                const { pages_scanned = 0, safe_actions_found = 0, manual_review_needed = 0 } = result.summary || {};
                
                let html = \`<p>Analysis scanned \${pages_scanned} pages. Found \${safe_actions_found} safe actions and \${manual_review_needed} items requiring review.</p>\`;
                
                if (requires_manual_review.length > 0) {
                    html += \`
                    <div class="result-section severity-medium">
                        <h4><input type="checkbox" onchange="QAApp.toggleAll('manualReviewChecks', this.checked)"> 👥 Manual Review Required (\${manual_review_needed})</h4>
                        <p>These pages may be integrated into your course. Review each item carefully.</p>
                        <div>
                        \${requires_manual_review.map((item, index) => \`
                            <div class="action-item">
                                <input type="checkbox" class="manualReviewChecks" data-action-index="\${index}" id="manual_\${index}">
                                <label for="manual_\${index}">
                                    <strong>Delete:</strong> "\${item.delete_page_title}"<br>
                                    <strong>Keep:</strong> "\${item.keep_page_title || 'Unknown'}"<br>
                                    \${item.similarity_percentage ? \`<small><strong>Similarity:</strong> \${item.similarity_percentage}</small><br>\` : ''}
                                    <small>\${item.reason}</small>
                                </label>
                            </div>
                        \`).join('')}
                        </div>
                    </div>\`;
                }

                if (safe_actions.length > 0) {
                     html += \`
                    <div class="result-section severity-safe">
                        <h4><input type="checkbox" onchange="QAApp.toggleAll('safeActionChecks', this.checked)" checked> ✅ Safe Actions Staged (\${safe_actions_found})</h4>
                        <p>These pages are unlinked orphans and can be safely removed.</p>
                        <div>
                        \${safe_actions.map((action, index) => \`
                            <div class="action-item">
                                <input type="checkbox" class="safeActionChecks" data-action-index="\${index}" id="safe_\${index}" checked>
                                <label for="safe_\${index}">
                                    <strong>Delete:</strong> "\${action.delete_page_title}"<br>
                                    <strong>Keep:</strong> "\${action.keep_page_title || 'Unknown'}"<br>
                                    \${action.similarity_percentage ? \`<small><strong>Similarity:</strong> \${action.similarity_percentage}</small><br>\` : ''}
                                    <small>\${action.reason}</small>
                                </label>
                            </div>
                        \`).join('')}
                        </div>
                    </div>\`;
                }
                
                if (safe_actions.length === 0 && requires_manual_review.length === 0) {
                    html += \`<div class="result-section severity-safe"><h4>🎉 No Duplicates Found!</h4><p>Excellent! This course is free of duplicate pages.</p></div>\`;
                }

                html += \`
                    <div style="margin-top: 24px; text-align: right;">
                        <button class="btn-secondary" onclick="QAApp.downloadReport()">📄 Download Report</button>
                        <button class="btn-primary" onclick="QAApp.executeSelectedActions()">Execute Selected Actions</button>
                    </div>\`;
                return html;
            }

            // --- NEW: Renderer for Assignment Validator ---
            function generateAssignmentResultsHtml(result) {
                const { safe_actions = [], requires_manual_review = [] } = result.findings || {};
                const { assignments_scanned = 0, total_violations_found = 0 } = result.summary || {};

                let html = \`<p>Analysis scanned \${assignments_scanned} assignments and found \${total_violations_found} potential issues.</p>\`;
                
                if (requires_manual_review.length > 0) {
                    html += \`
                    <div class="result-section severity-high">
                        <h4><input type="checkbox" onchange="QAApp.toggleAll('manualReviewChecks', this.checked)"> 👥 Manual Review Required (\${requires_manual_review.length})</h4>
                        <p>These issues are high-risk or require an instructor's decision to resolve.</p>
                        <div>
                        \${requires_manual_review.map((item, index) => \`
                            <div class="action-item">
                                <input type="checkbox" class="manualReviewChecks" data-action-index="\${index}" id="manual_\${index}">
                                <label for="manual_\${index}">
                                    <strong>\${item.assignment_name}</strong>
                                    <span class="severity-badge \${(item.severity || 'low').toLowerCase()}">\${item.severity}</span>
                                    <br>
                                    <small>\${item.reason}</small>
                                </label>
                            </div>
                        \`).join('')}
                        </div>
                    </div>\`;
                }

                if (safe_actions.length > 0) {
                     html += \`
                    <div class="result-section severity-safe">
                        <h4><input type="checkbox" onchange="QAApp.toggleAll('safeActionChecks', this.checked)" checked> ✅ Safe Fixes Staged (\${safe_actions.length})</h4>
                        <p>These are low-risk issues that can be fixed automatically.</p>
                        <div>
                        \${safe_actions.map((action, index) => \`
                            <div class="action-item">
                                <input type="checkbox" class="safeActionChecks" data-action-index="\${index}" id="safe_\${index}" checked>
                                <label for="safe_\${index}">
                                    <strong>\${action.assignment_name}</strong>
                                    <span class="severity-badge \${(action.severity || 'low').toLowerCase()}">\${action.severity}</span>
                                    <br>
                                    <small>\${action.reason}</small>
                                </label>
                            </div>
                        \`).join('')}
                        </div>
                    </div>\`;
                }

                if (safe_actions.length === 0 && requires_manual_review.length === 0) {
                    html += \`<div class="result-section severity-safe"><h4>🎉 No Issues Found!</h4><p>Excellent! All assignments passed QA validation.</p></div>\`;
                }

                html += \`
                    <div style="margin-top: 24px; text-align: right;">
                        <button class="btn-secondary" onclick="QAApp.downloadReport()">📄 Download Report</button>
                        <button class="btn-primary" onclick="QAApp.executeSelectedActions()">Execute Selected Fixes</button>
                    </div>\`;
                return html;
            }

            function generateGenericResultsHtml(result) { /* Fallback, remains the same */ }

            function generateEmptyGroupsModulesResultsHtml(result) {
                const { safe_actions = [], requires_manual_review = [] } = result.findings || {};
                const { groups_scanned = 0, modules_scanned = 0, safe_actions_found = 0, manual_review_needed = 0, weighted_course = false } = result.summary || {};

                let html = \`<p>Scanned \${groups_scanned} assignment groups and \${modules_scanned} modules.\${weighted_course ? ' Weighted grading is enabled in this course.' : ''}</p>\`;

                if (requires_manual_review.length > 0) {
                    html += \`
                    <div class="result-section severity-medium">
                        <h4><input type="checkbox" onchange="QAApp.toggleAll('manualReviewChecks', this.checked)"> 👥 Manual Review Required (\${requires_manual_review.length})</h4>
                        <p>These items are published, referenced by prerequisites, or have grading weight. Review carefully.</p>
                        <div>
                        \${requires_manual_review.map((item, index) => \`
                            <div class="action-item">
                                <input type="checkbox" class="manualReviewChecks" data-action-index="\${index}" id="manual_\${index}">
                                <label for="manual_\${index}">
                                    <div class="action-title">\${item.type === 'delete_assignment_group' ? 'Assignment Group' : 'Module'}: \${item.group_name || item.module_name}</div>
                                    <div class="action-desc">\${item.reason}</div>
                                </label>
                            </div>
                        \`).join('')}
                        </div>
                    </div>\`;
                }

                if (safe_actions.length > 0) {
                    html += \`
                    <div class="result-section severity-safe">
                        <h4><input type="checkbox" onchange="QAApp.toggleAll('safeActionChecks', this.checked)" checked> ✅ Safe Deletions Staged (\${safe_actions_found || safe_actions.length})</h4>
                        <p>These items are empty and safe to remove.</p>
                        <div>
                        \${safe_actions.map((action, index) => \`
                            <div class="action-item">
                                <input type="checkbox" class="safeActionChecks" data-action-index="\${index}" id="safe_\${index}" checked>
                                <label for="safe_\${index}">
                                    <div class="action-title">\${action.type === 'delete_assignment_group' ? 'Assignment Group' : 'Module'}: \${action.group_name || action.module_name}</div>
                                    <div class="action-desc">\${action.reason}</div>
                                </label>
                            </div>
                        \`).join('')}
                        </div>
                    </div>\`;
                }

                if (safe_actions.length === 0 && requires_manual_review.length === 0) {
                    html += \`<div class="result-section severity-safe"><h4>🎉 Nothing to Clean!</h4><p>No empty assignment groups or modules were found.</p></div>\`;
                }

                html += \`
                    <div style="margin-top: 24px; text-align: right;">
                        <button class="btn-secondary" onclick="QAApp.downloadReport()">📄 Download Report</button>
                        <button class="btn-primary" onclick="QAApp.executeSelectedActions()">Delete Selected Items</button>
                    </div>\`;

                return html;
            }
            
            // --- NEW: Renderer for Assessment Date Updater ---
            function generateAssessmentDateResultsHtml(result) {
                const { safe_actions = [], requires_manual_review = [] } = result.findings || {};
                const { pages_scanned = 0, dates_found = 0, replacements_proposed = 0 } = result.summary || {};

                let html = \`<p>Analysis scanned \${pages_scanned} summary pages and found \${dates_found} date references that can be updated.</p>\`;
                
                if (requires_manual_review.length > 0) {
                    html += \`
                    <div class="result-section severity-medium">
                        <h4><input type="checkbox" onchange="QAApp.toggleAll('manualReviewChecks', this.checked)"> 📅 Date Replacements (\${replacements_proposed})</h4>
                        <p>These pages contain hard-coded dates that can be replaced with week-based deadlines for consistency.</p>
                        <div>
                        \${requires_manual_review.map((item, index) => \`
                            <div class="action-item">
                                <input type="checkbox" class="manualReviewChecks" data-action-index="\${index}" id="manual_\${index}">
                                <label for="manual_\${index}">
                                    <strong>Page:</strong> "\${item.page_title}"<br>
                                    <strong>Module:</strong> "\${item.module_name || 'Unknown'}"<br>
                                    <strong>Changes:</strong> \${item.changes ? item.changes.join(', ') : 'Date replacement'}<br>
                                    <small>\${item.reason}</small>
                                </label>
                            </div>
                        \`).join('')}
                        </div>
                    </div>\`;
                }
                
                if (safe_actions.length > 0) {
                    html += \`
                    <div class="result-section severity-safe">
                        <h4><input type="checkbox" onchange="QAApp.toggleAll('safeActionChecks', this.checked)" checked> ✅ Safe Actions Staged (\${safe_actions.length})</h4>
                        <p>These actions can be safely executed.</p>
                        <div>
                        \${safe_actions.map((action, index) => \`
                            <div class="action-item">
                                <input type="checkbox" class="safeActionChecks" data-action-index="\${index}" id="safe_\${index}" checked>
                                <label for="safe_\${index}">
                                    <strong>Action:</strong> \${action.description}<br>
                                    <small>\${action.reason}</small>
                                </label>
                            </div>
                        \`).join('')}
                        </div>
                    </div>\`;
                }
                
                if (requires_manual_review.length === 0 && safe_actions.length === 0) {
                    html += \`<div class="result-section severity-safe"><h4>🎉 No Date Updates Needed!</h4><p>Excellent! All assessment dates are already using week-based references.</p></div>\`;
                }

                html += \`
                    <div style="margin-top: 24px; text-align: right;">
                        <button class="btn-secondary" onclick="QAApp.downloadReport()">📄 Download Report</button>
                        <button class="btn-primary" onclick="QAApp.executeSelectedActions()">Execute Selected Updates</button>
                    </div>\`;
                return html;
            }
            
            // --- NEW: Renderer for Table Caption Checker ---
            function generateTableCaptionResultsHtml(result) {
                const { safe_actions = [], requires_manual_review = [] } = result.findings || {};
                const { pages_scanned = 0, tables_found = 0, issues_found = 0, design_standards_loaded = false } = result.summary || {};

                let html = \`<p>Analysis scanned \${pages_scanned} pages and found \${tables_found} tables with class "acuo-table". Found \${issues_found} caption compliance issues.</p>\`;
                
                if (!design_standards_loaded) {
                    html += \`<div class="result-section severity-medium"><h4>⚠️ Design Standards Not Available</h4><p>The ACU Online Design Library could not be accessed. Analysis will use basic standards.</p></div>\`;
                }
                
                if (requires_manual_review.length > 0) {
                    html += \`
                    <div class="result-section severity-medium">
                        <h4>📋 Caption Compliance Issues (\${issues_found})</h4>
                        <p>These tables need caption improvements to meet ACU design standards. Click on any issue to open the page in Canvas for manual editing.</p>
                        <div>
                        \${requires_manual_review.map((item, index) => \`
                            <div class="action-item clickable" onclick="QAApp.openCanvasPage('\${item.page_url}')" style="cursor: pointer;">
                                <div class="action-content">
                                    <strong>Page:</strong> "\${item.page_title}"<br>
                                    <strong>Issue:</strong> \${item.description}<br>
                                    <strong>Table:</strong> \${item.table_preview || 'Unknown'}<br>
                                    <strong>Recommendation:</strong> \${item.recommendation}<br>
                                    <small>\${item.reason}</small>
                                </div>
                                <div class="action-icon">🔗</div>
                            </div>
                        \`).join('')}
                        </div>
                    </div>\`;
                }
                
                if (safe_actions.length > 0) {
                    html += \`
                    <div class="result-section severity-safe">
                        <h4>✅ Safe Actions Staged (\${safe_actions.length})</h4>
                        <p>These actions can be safely executed.</p>
                        <div>
                        \${safe_actions.map((action, index) => \`
                            <div class="action-item">
                                <div class="action-content">
                                    <strong>Action:</strong> \${action.description}<br>
                                    <small>\${action.reason}</small>
                                </div>
                            </div>
                        \`).join('')}
                        </div>
                    </div>\`;
                }
                
                if (requires_manual_review.length === 0 && safe_actions.length === 0) {
                    html += \`<div class="result-section severity-safe"><h4>🎉 All Tables Compliant!</h4><p>Excellent! All tables with class "acuo-table" have proper captions that meet ACU design standards.</p></div>\`;
                }

                html += \`
                    <div style="margin-top: 24px; text-align: right;">
                        <button class="btn-secondary" onclick="QAApp.downloadReport()">📄 Download Report</button>
                        <button class="btn-primary" onclick="QAApp.showManualGuidance()">📋 Show Manual Fixes Guide</button>
                    </div>\`;
                return html;
            }

            // --- NEW: Renderer for Syllabus ACUO Attribution Remover ---
            function generateSyllabusAttributionResultsHtml(result) {
                const { safe_actions = [], requires_manual_review = [] } = result.findings || {};
                const { items_scanned = 0, issues_found = 0, safe_actions_found = 0, manual_review_needed = 0 } = result.summary || {};

                let html = \`<p>Analyzed \${items_scanned} syllabus. Found \${issues_found} occurrence(s) of \"(ACU Online, YYYY)\".</p>\`;

                if (requires_manual_review.length > 0) {
                    html += \`
                    <div class=\"result-section severity-medium\">
                        <h4><input type=\"checkbox\" onchange=\"QAApp.toggleAll('manualReviewChecks', this.checked)\"> 👥 Manual Review Required (\${manual_review_needed})</h4>
                        <p>These occurrences appear in sensitive contexts (e.g., headings, quotes, references) and should be reviewed manually.</p>
                        <div>
                        \${requires_manual_review.map((item, index) => \`
                            <div class=\"action-item\">
                                <input type=\"checkbox\" class=\"manualReviewChecks\" data-action-index=\"\${index}\" id=\"manual_\${index}\">\n
                                <label for=\"manual_\${index}\">\n
                                    <div class=\"action-desc\"><strong>Excerpt:</strong> \${item.excerpt || 'N/A'}</div>\n
                                    <div class=\"action-desc\"><small>\${item.reason || 'Manual review recommended'} </small></div>\n
                                </label>
                            </div>
                        \`).join('')}
                        </div>
                    </div>\`;
                }

                if (safe_actions.length > 0) {
                    html += \`
                    <div class=\"result-section severity-safe\">\n
                        <h4><input type=\"checkbox\" onchange=\"QAApp.toggleAll('safeActionChecks', this.checked)\" checked> ✅ Safe Removals Staged (\${safe_actions_found || safe_actions.length})</h4>
                        <p>Occurrences in plain paragraph contexts can be removed safely.</p>
                        <div>
                        \${safe_actions.map((action, index) => \`
                            <div class=\"action-item\">
                                <input type=\"checkbox\" class=\"safeActionChecks\" data-action-index=\"\${index}\" id=\"safe_\${index}\" checked>
                                <label for=\"safe_\${index}\">\n
                                    <div class=\"action-title\">Remove Syllabus Attribution</div>\n
                                    <div class=\"action-desc\"><small>\${action.reason || 'Safe to remove'} </small></div>\n
                                </label>
                            </div>
                        \`).join('')}
                        </div>
                    </div>\`;
                }

                if ((safe_actions.length === 0) && (requires_manual_review.length === 0)) {
                    html += \`<div class=\"result-section severity-safe\"><h4>🎉 No Attributions Found!</h4><p>The syllabus does not contain the target ACU Online attribution.</p></div>\`;
                }

                html += \`
                    <div style=\"margin-top: 24px; text-align: right;\">\n
                        <button class=\"btn-secondary\" onclick=\"QAApp.downloadReport()\">📄 Download Report</button>\n
                        <button class=\"btn-primary\" onclick=\"QAApp.executeSelectedActions()\">Execute Selected Actions</button>\n
                    </div>\`;

                return html;
            }

            // --- NEW: Renderer for Rubric Cleanup ---
            function generateRubricCleanupResultsHtml(result) {
                const { safe_actions = [], requires_manual_review = [] } = result.findings || {};
                const { rubrics_scanned = 0, safe_actions_found = 0, manual_review_needed = 0 } = result.summary || {};

                let html = \`<p>Analyzed \${rubrics_scanned} rubrics. Found \${safe_actions_found} safe deletions and \${manual_review_needed} items for manual review.</p>\`;

                if (requires_manual_review.length > 0) {
                    html += \`
                    <div class=\"result-section severity-medium\">
                        <h4><input type=\"checkbox\" onchange=\"QAApp.toggleAll('manualReviewChecks', this.checked)\"> 👥 Manual Review Required (\${manual_review_needed})</h4>
                        <p>Duplicates, protected items, or outdated rubrics that may need human decision.</p>
                        <div>
                        \${requires_manual_review.map((item, index) => \`
                            <div class=\"action-item\">
                                <input type=\"checkbox\" class=\"manualReviewChecks\" data-action-index=\"\${index}\" id=\"manual_\${index}\">
                                <label for=\"manual_\${index}\">
                                    \${item.type === 'duplicate_rubric_group' ? \`
                                        <strong>Duplicate Group:</strong> Keep \"\${item.keep_rubric_title}\"<br>
                                        <small>Delete candidates: \${(item.delete_candidates||[]).map(c => \`#\${c.rubric_id} \${c.rubric_title}\`).join(', ') || 'N/A'}</small>
                                    \` : \`
                                        <strong>Rubric:</strong> \"\${item.rubric_title || 'Unknown'}\"<br>
                                        <small>\${item.reason || 'Review recommended'}</small>
                                    \`}
                                </label>
                                \${item.canvas_url ? \`<div class=\"action-icon\"><a href=\"\${item.canvas_url}\" target=\"_blank\" rel=\"noopener\">🔗</a></div>\` : ''}
                            </div>
                        \`).join('')}
                        </div>
                    </div>\`;
                }

                if (safe_actions.length > 0) {
                    html += \`
                    <div class=\"result-section severity-safe\">
                        <h4><input type=\"checkbox\" onchange=\"QAApp.toggleAll('safeActionChecks', this.checked)\" checked> ✅ Safe Deletions Staged (\${safe_actions_found || safe_actions.length})</h4>
                        <p>These rubrics have no associations or usage and are old enough to be safely removed.</p>
                        <div>
                        \${safe_actions.map((action, index) => \`
                            <div class=\"action-item\">
                                <input type=\"checkbox\" class=\"safeActionChecks\" data-action-index=\"\${index}\" id=\"safe_\${index}\" checked>
                                <label for=\"safe_\${index}\">
                                    <strong>Rubric:</strong> \"\${action.rubric_title}\" (ID: \${action.rubric_id})<br>
                                    <small>\${action.reason || 'Safe to delete'}</small>
                                </label>
                                \${action.canvas_url ? \`<div class=\"action-icon\"><a href=\"\${action.canvas_url}\" target=\"_blank\" rel=\"noopener\">🔗</a></div>\` : ''}
                            </div>
                        \`).join('')}
                        </div>
                    </div>\`;
                }

                if (safe_actions.length === 0 && requires_manual_review.length === 0) {
                    html += \`<div class=\"result-section severity-safe\"><h4>🎉 Nothing to Clean!</h4><p>No rubrics require attention.</p></div>\`;
                }

                html += \`
                    <div style=\"margin-top: 24px; text-align: right;\">
                        <button class=\"btn-secondary\" onclick=\"QAApp.downloadReport()\">📄 Download Report</button>
                        <button class=\"btn-primary\" onclick=\"QAApp.executeSelectedActions()\">Delete Selected Rubrics</button>
                    </div>\`;

                return html;
            }
            
            // --- CORE LOGIC ---
            
            function startAnalysis(taskId) {
                console.log('🔍 startAnalysis called with taskId:', taskId);
                console.log('📊 Request details:', { taskId, courseId, userId });
                currentTaskId = taskId;
                
                showProgress('Initializing analysis...', 'Preparing to analyze course content');
                
                fetch('/execute', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ taskId, courseId, userId })
                })
                .then(response => {
                    console.log('📡 Server response status:', response.status);
                    return response.json();
                })
                .then(data => {
                    console.log('📝 Analysis response received:', data);
                    hideProgress();
                    if (data.success) {
                        showResults(taskId, data.result);
                    } else {
                        showError(data.error || 'Analysis failed');
                    }
                })
                .catch(error => {
                    console.error('💥 Network error:', error);
                    hideProgress();
                    showError('Network error: ' + error.message);
                });
            }
            
            function closePreview() {
                document.getElementById('analysisPreview').classList.remove('active');
            }
            
            function proceedWithAnalysis() {
                console.log('🚀 proceedWithAnalysis called, currentTaskId:', currentTaskId);
                closePreview();
                if (currentTaskId) {
                    console.log('✅ Starting analysis for task:', currentTaskId);
                    startAnalysis(currentTaskId);
                } else {
                    console.error('❌ currentTaskId is null/undefined!');
                }
            }
            
            function executeSelectedActions() {
                const safeActions = Array.from(document.querySelectorAll('.safeActionChecks:checked'))
                    .map(checkbox => currentAnalysisResult.findings.safe_actions[parseInt(checkbox.dataset.actionIndex)]);
                const manualActions = Array.from(document.querySelectorAll('.manualReviewChecks:checked'))
                    .map(checkbox => currentAnalysisResult.findings.requires_manual_review[parseInt(checkbox.dataset.actionIndex)]);
                
                const allActions = [...safeActions, ...manualActions];
                
                if (allActions.length === 0) {
                    alert('Please select at least one action to execute.');
                    return;
                }
                
                showProgress('Executing selected actions...', 'This may take a few moments');
                
                fetch('/execute-approved', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ 
                        taskId: currentTaskId, 
                        courseId, 
                        userId, 
                        approvedActions: allActions 
                    })
                })
                .then(response => response.json())
                .then(data => {
                    hideProgress();
                    if (data.success) {
                        showExecutionResults(data.result, allActions.length);
                    } else {
                        showError(data.error || 'Execution failed');
                    }
                })
                .catch(error => {
                    hideProgress();
                    showError('Network error: ' + error.message);
                });
            }

            // NEW: Show detailed execution results with confirmation and download options
            function showExecutionResults(executionResult, totalRequested) {
                const container = document.getElementById('resultsContainer');
                document.getElementById('resultsTitle').textContent = 'Execution Complete - ' + QA_TASKS[currentTaskId].name;
                
                const { summary = {}, results = {} } = executionResult;
                const successful = summary.successful || 0;
                const failed = summary.failed || 0;
                const successfulFixes = results.successful_fixes || [];
                const failedFixes = results.failed_fixes || [];
                
                let html = '<div class="execution-summary">' +
                    '<div class="execution-stats">' +
                    '<div class="stat-card ' + (failed === 0 ? 'success' : 'mixed') + '">' +
                    '<h3>' + successful + ' of ' + totalRequested + ' Actions Completed Successfully</h3>' +
                    (failed > 0 ? '<p class="failure-note">' + failed + ' actions failed - see details below</p>' : '') +
                    '<p class="timestamp">Completed: ' + new Date().toLocaleString() + '</p>' +
                    '</div></div></div>';

                if (successfulFixes.length > 0) {
                    html += '<div class="result-section severity-safe">' +
                        '<h4>✅ Successfully Applied Changes (' + successful + ')</h4>' +
                        '<p>These changes have been applied to your course and are now active.</p>' +
                        '<div class="execution-details">';
                    
                    successfulFixes.forEach(fix => {
                        html += '<div class="execution-item success">' +
                            '<div class="execution-icon">✅</div>' +
                            '<div class="execution-content">' +
                            '<strong>' + (fix.assignment_name || 'Unknown') + '</strong><br>' +
                            '<small>' + (fix.reason || 'No details') + '</small>';
                        if (fix.fix_action) {
                            html += '<br><span class="fix-detail">Applied: ' + getFixActionDescription(fix.fix_action) + '</span>';
                        }
                        html += '</div></div>';
                    });
                    
                    html += '</div></div>';
                }

                if (failedFixes.length > 0) {
                    html += '<div class="result-section severity-high">' +
                        '<h4>❌ Failed Changes (' + failed + ')</h4>' +
                        '<p>These changes could not be applied automatically. Manual review may be required.</p>' +
                        '<div class="execution-details">';
                    
                    failedFixes.forEach(fix => {
                        html += '<div class="execution-item failure">' +
                            '<div class="execution-icon">❌</div>' +
                            '<div class="execution-content">' +
                            '<strong>' + (fix.assignment_name || 'Unknown Assignment') + '</strong><br>' +
                            '<small>Reason: ' + (fix.failure_reason || 'Unknown error') + '</small>';
                        if (fix.reason) {
                            html += '<br><span class="original-issue">Original Issue: ' + fix.reason + '</span>';
                        }
                        html += '</div></div>';
                    });
                    
                    html += '</div></div>';
                }

                html += '<div class="execution-actions">' +
                    '<div class="action-buttons">' +
                    '<button class="btn-secondary" onclick="QAApp.downloadExecutionReport()">📄 Download Execution Report</button>' +
                    '<button class="btn-secondary" onclick="QAApp.runNewAnalysis()">🔄 Run New Analysis</button>' +
                    '<button class="btn-primary" onclick="QAApp.returnToTasks()">Return to QA Tasks</button>' +
                    '</div>';
                
                if (failed > 0) {
                    html += '<div class="next-steps">' +
                        '<h4>📋 Recommended Next Steps:</h4>' +
                        '<ul>' +
                        '<li>Review the failed changes above</li>' +
                        '<li>Check Canvas permissions for API access</li>' +
                        '<li>Consider applying failed changes manually in Canvas</li>' +
                        '<li>Download the execution report for your records</li>' +
                        '</ul></div>';
                } else {
                    html += '<div class="success-message">' +
                        '<h4>🎉 All Changes Applied Successfully!</h4>' +
                        '<p>Your course has been updated according to QA standards. Students will see these improvements immediately.</p>' +
                        '</div>';
                }
                
                html += '</div>';
                
                document.getElementById('resultsContent').innerHTML = html;
                container.style.display = 'block';
                container.scrollIntoView({ behavior: 'smooth' });
                
                // Store execution results for download
                window.currentExecutionResult = executionResult;
            }

            // NEW: Helper function to describe fix actions in human terms
            function getFixActionDescription(fixAction) {
                const actionType = fixAction.type;
                switch (actionType) {
                    case 'update_points':
                        return 'Set points to ' + fixAction.value;
                    case 'update_grading_type':
                        return 'Changed grading type to ' + fixAction.value;
                    case 'update_attempts':
                        return 'Set attempts to ' + (fixAction.value === -1 ? 'unlimited' : fixAction.value);
                    case 'add_print_button':
                        return 'Added standard print button to description';
                    default:
                        return 'Applied ' + actionType;
                }
            }

            // NEW: Download execution report
            function downloadExecutionReport() {
                if (!window.currentExecutionResult) {
                    alert('No execution results available for download');
                    return;
                }

                try {
                    const result = window.currentExecutionResult;
                    const workbook = XLSX.utils.book_new();
                    
                    // Sheet 1: Execution Summary
                    const summaryData = [
                        { 'Field': 'Task Type', 'Value': QA_TASKS[currentTaskId].name },
                        { 'Field': 'Course ID', 'Value': courseId },
                        { 'Field': 'Executed By', 'Value': userName },
                        { 'Field': 'Date', 'Value': new Date().toLocaleDateString() },
                        { 'Field': 'Time', 'Value': new Date().toLocaleTimeString() },
                        { 'Field': 'Total Actions', 'Value': (result.summary?.successful || 0) + (result.summary?.failed || 0) },
                        { 'Field': 'Successful', 'Value': result.summary?.successful || 0 },
                        { 'Field': 'Failed', 'Value': result.summary?.failed || 0 },
                        { 'Field': 'Success Rate', 'Value': calculateEnhancedSuccessRate(result) + '%' }
                    ];
                    
                    const summarySheet = XLSX.utils.json_to_sheet(summaryData);
                    XLSX.utils.book_append_sheet(workbook, summarySheet, 'Summary');
                    
                    // Sheet 2: All Changes (for analysis)
                    const allChanges = [
                        ...(result.results?.successful_fixes || []).map(fix => ({
                            'Status': 'SUCCESS',
                            'Item Name': fix.assignment_name || 'Unknown',
                            'Canvas Link': generateEnhancedCanvasLink(fix),
                            'Issue': fix.reason || 'QA Issue',
                            'Action Applied': getFixActionDescription(fix.fix_action),
                            'Item ID': fix.assignment_id || 'N/A',
                            'Timestamp': new Date().toISOString()
                        })),
                        ...(result.results?.failed_fixes || []).map(fix => ({
                            'Status': 'FAILED',
                            'Item Name': fix.assignment_name || 'Unknown',
                            'Canvas Link': generateEnhancedCanvasLink(fix),
                            'Issue': fix.reason || 'QA Issue',
                            'Failure Reason': fix.failure_reason || 'Unknown error',
                            'Item ID': fix.assignment_id || 'N/A',
                            'Timestamp': new Date().toISOString()
                        }))
                    ];
                    
                    if (allChanges.length > 0) {
                        const changesSheet = XLSX.utils.json_to_sheet(allChanges);
                        XLSX.utils.book_append_sheet(workbook, changesSheet, 'All Changes');
                    }
                    
                    const timestamp = new Date().toISOString().slice(0,19).replace(/[:\-]/g, '');
                    const filename = \`QA_Execution_\${currentTaskId}_\${courseId}_\${timestamp}.xlsx\`;
                    XLSX.writeFile(workbook, filename);
                    
                } catch (error) {
                    console.warn('Enhanced execution report failed:', error);
                    // Fallback to basic report
                    const result = window.currentExecutionResult;
                    const { summary = {}, results = {} } = result;
                    const successfulFixes = results.successful_fixes || [];
                    const failedFixes = results.failed_fixes || [];

                    const reportData = [
                        { 'Report Type': 'QA Execution Results' },
                        { 'Task': QA_TASKS[currentTaskId].name },
                        { 'Course ID': courseId },
                        { 'User': userName },
                        { 'Execution Date': new Date().toISOString() }
                    ];

                    const workbook = XLSX.utils.book_new();
                    const worksheet = XLSX.utils.json_to_sheet(reportData);
                    XLSX.utils.book_append_sheet(workbook, worksheet, 'Execution Report');
                    XLSX.writeFile(workbook, 'qa_execution_report_' + currentTaskId + '_' + Date.now() + '.xlsx');
                }
            }

            // NEW: Run fresh analysis
            function runNewAnalysis() {
                window.currentExecutionResult = null;
                document.getElementById('resultsContainer').style.display = 'none';
                startAnalysis(currentTaskId);
            }

            // NEW: Return to task selection
            function returnToTasks() {
                window.currentExecutionResult = null;
                currentAnalysisResult = null;
                currentTaskId = null;
                document.getElementById('resultsContainer').style.display = 'none';
                window.scrollTo({ top: 0, behavior: 'smooth' });
            }
            
            function downloadReport() {
                if (!currentAnalysisResult) return;
                
                try {
                    const workbook = XLSX.utils.book_new();
                    
                    // Sheet 1: Analysis Summary (for records)
                    const summaryData = [
                        { 'Field': 'Task Type', 'Value': QA_TASKS[currentTaskId].name },
                        { 'Field': 'Course ID', 'Value': courseId },
                        { 'Field': 'Analyst', 'Value': userName },
                        { 'Field': 'Date', 'Value': new Date().toLocaleDateString() },
                        { 'Field': 'Time', 'Value': new Date().toLocaleTimeString() },
                        { 'Field': 'Items Scanned', 'Value': currentAnalysisResult.summary?.pages_scanned || currentAnalysisResult.summary?.assignments_scanned || 0 },
                        { 'Field': 'Issues Found', 'Value': (currentAnalysisResult.findings?.safe_actions?.length || 0) + (currentAnalysisResult.findings?.requires_manual_review?.length || 0) },
                        { 'Field': 'Auto-Fixable', 'Value': currentAnalysisResult.findings?.safe_actions?.length || 0 },
                        { 'Field': 'Manual Review', 'Value': currentAnalysisResult.findings?.requires_manual_review?.length || 0 }
                    ];
                    
                    const summarySheet = XLSX.utils.json_to_sheet(summaryData);
                    XLSX.utils.book_append_sheet(workbook, summarySheet, 'Summary');
                    
                    // Sheet 2: All Issues (for filtering/sorting)
                    const allIssues = [
                        ...(currentAnalysisResult.findings?.safe_actions || []).map(item => ({
                            'Category': 'Auto-Fixable',
                            'Priority': getEnhancedPriority(item),
                            'Item Name': item.assignment_name || item.delete_page_title || 'Unknown',
                            'Canvas Link': generateEnhancedCanvasLink(item),
                            'Issue Description': item.reason || 'No description',
                            'Item Type': item.assignment_name ? 'Assignment' : 'Page',
                            'Item ID': item.assignment_id || item.page_id || 'N/A',
                            'Risk Level': 'Low',
                            'Action Required': 'Approve for execution'
                        })),
                        ...(currentAnalysisResult.findings?.requires_manual_review || []).map(item => ({
                            'Category': 'Manual Review',
                            'Priority': getEnhancedPriority(item),
                            'Item Name': item.assignment_name || item.delete_page_title || 'Unknown',
                            'Canvas Link': generateEnhancedCanvasLink(item),
                            'Issue Description': item.reason || 'Requires investigation',
                            'Item Type': item.assignment_name ? 'Assignment' : 'Page',
                            'Item ID': item.assignment_id || item.page_id || 'N/A',
                            'Risk Level': getEnhancedRiskLevel(item),
                            'Action Required': 'Manual decision needed'
                        }))
                    ];
                    
                    if (allIssues.length > 0) {
                        const issuesSheet = XLSX.utils.json_to_sheet(allIssues);
                        XLSX.utils.book_append_sheet(workbook, issuesSheet, 'All Issues');
                    }
                    
                    const timestamp = new Date().toISOString().slice(0,19).replace(/[:\-]/g, '');
                    const filename = \`QA_Analysis_\${currentTaskId}_\${courseId}_\${timestamp}.xlsx\`;
                    XLSX.writeFile(workbook, filename);
                    
                } catch (error) {
                    console.warn('Enhanced report failed:', error);
                    // Fallback to basic report
                    const workbook = XLSX.utils.book_new();
                    const worksheet = XLSX.utils.json_to_sheet([
                        { 'Analysis Type': QA_TASKS[currentTaskId].name },
                        { 'Course ID': courseId },
                        { 'User': userName },
                        { 'Timestamp': new Date().toISOString() }
                    ]);
                    XLSX.utils.book_append_sheet(workbook, worksheet, 'QA Report');
                    XLSX.writeFile(workbook, 'qa_report_' + currentTaskId + '_' + Date.now() + '.xlsx');
                }
            }
            
            function toggleAll(className, checked) {
                document.querySelectorAll('.' + className).forEach(checkbox => {
                    checkbox.checked = checked;
                });
            }
            
            function openCanvasPage(pageUrl) {
                if (pageUrl && pageUrl !== 'N/A') {
                    window.open(pageUrl, '_blank');
                } else {
                    alert('Page URL not available for this item.');
                }
            }
            
            function showManualGuidance() {
                if (!currentAnalysisResult) {
                    alert('No analysis results available');
                    return;
                }
                
                const issues = currentAnalysisResult.findings?.requires_manual_review || [];
                if (issues.length === 0) {
                    alert('No manual fixes needed - all items are compliant!');
                    return;
                }
                
                const container = document.getElementById('resultsContainer');
                document.getElementById('resultsTitle').textContent = 'Manual Fixes Guide - ' + QA_TASKS[currentTaskId].name;
                
                let html = \`
                    <div class="result-section severity-medium">
                        <h4>📋 Manual Fixes Required (\${issues.length} items)</h4>
                        <p>Canvas API limitations prevent automatic table caption updates. Follow these steps to fix each issue manually:</p>
                        
                        <div class="manual-steps">
                            <h5>🔧 Step-by-Step Process:</h5>
                            <ol>
                                <li><strong>Open the page</strong> - Click on any issue below to open the page in Canvas</li>
                                <li><strong>Switch to HTML editor</strong> - Click the HTML editor button in Canvas</li>
                                <li><strong>Locate the table</strong> - Find the table with class "acuo-table"</li>
                                <li><strong>Add/modify caption</strong> - Add or update the &lt;caption&gt; element</li>
                                <li><strong>Apply styling</strong> - Add CSS classes: "sm-font", "text-muted"</li>
                                <li><strong>Include citation</strong> - Add proper citation: "(Source, Year)"</li>
                                <li><strong>Save and publish</strong> - Save changes and publish the page</li>
                            </ol>
                        </div>
                        
                        <div class="examples">
                            <h5>💡 Examples:</h5>
                            <div class="example-item">
                                <strong>✅ Good:</strong> <code>&lt;caption class="sm-font text-muted"&gt;Table 1: Student Performance Data (ACU Online, 2024)&lt;/caption&gt;</code>
                            </div>
                            <div class="example-item">
                                <strong>❌ Bad:</strong> <code>&lt;caption&gt;Table 1&lt;/caption&gt;</code>
                            </div>
                            <div class="example-item">
                                <strong>❌ Missing:</strong> No caption element found
                            </div>
                        </div>
                    </div>
                    
                    <div class="result-section severity-medium">
                        <h4>📋 Issues to Fix (\${issues.length})</h4>
                        <p>Click on any issue to open the page in Canvas for editing:</p>
                        <div>\`;
                
                issues.forEach((item, index) => {
                    html += \`
                        <div class="action-item clickable" onclick="QAApp.openCanvasPage('\${item.page_url}')" style="cursor: pointer;">
                            <div class="action-content">
                                <strong>Page:</strong> "\${item.page_title}"<br>
                                <strong>Issue:</strong> \${item.description}<br>
                                <strong>Current:</strong> \${item.current_value}<br>
                                <strong>Suggested:</strong> \${item.suggested_value}<br>
                                <small>\${item.recommendation}</small>
                            </div>
                            <div class="action-icon">🔗</div>
                        </div>
                    \`;
                });
                
                html += \`
                        </div>
                    </div>
                    
                    <div style="margin-top: 24px; text-align: right;">
                        <button class="btn-secondary" onclick="QAApp.downloadReport()">📄 Download Report</button>
                        <button class="btn-primary" onclick="QAApp.returnToResults()">← Back to Results</button>
                    </div>
                \`;
                
                document.getElementById('resultsContent').innerHTML = html;
                container.style.display = 'block';
                container.scrollIntoView({ behavior: 'smooth' });
            }
            
            function returnToResults() {
                if (currentAnalysisResult) {
                    showResults(currentTaskId, currentAnalysisResult);
                }
            }
            
            function initializeTaskCards() {
                console.log('🔧 Initializing task cards...');
                console.log('🔧 QA_TASKS available:', typeof QA_TASKS);
                console.log('🔧 QA_TASKS keys:', Object.keys(QA_TASKS));
                document.querySelectorAll('.task-card').forEach(card => {
                    card.addEventListener('click', function() {
                        const taskId = this.dataset.taskId;
                        console.log('🎯 Task card clicked:', taskId);
                        console.log('🔍 Available tasks:', Object.keys(QA_TASKS));
                        console.log('🔍 QA_TASKS object:', QA_TASKS);
                        console.log('🔍 QA_TASKS[taskId]:', QA_TASKS[taskId]);
                        if (taskId) {
                            currentTaskId = taskId; // Now accessible!
                            console.log('✅ currentTaskId set to:', currentTaskId);
                            if (QA_TASKS[taskId]) {
                                document.getElementById('previewTitle').textContent = QA_TASKS[taskId].name;
                            document.getElementById('previewContent').innerHTML = 
                                '<p>' + QA_TASKS[taskId].description + '</p>' +
                                '<div style="margin: 20px 0; padding: 16px; background: var(--acu-cream-dark); border-radius: 6px; border-left: 4px solid var(--acu-gold);">' +
                                '<h4 style="margin: 0 0 8px 0; color: var(--acu-deep-purple);">📋 What to Expect:</h4>' +
                                '<ul style="margin: 0; padding-left: 20px; color: var(--acu-purple);">' +
                                (taskId === 'find-duplicate-pages' ? 
                                    '<li>Scan all course pages for duplicate content</li>' +
                                    '<li>Check for protective inbound links</li>' +
                                    '<li>Categorize findings by safety level</li>' +
                                    '<li>Provide detailed comparison for each duplicate</li>' :
                                    taskId === 'validate-assignment-settings' ?
                                    '<li>Analyze all assignment configurations</li>' +
                                    '<li>Check points, grading types, and due dates</li>' +
                                    '<li>Identify potential student confusion points</li>' +
                                    '<li>Recommend improvements for clarity</li>' :
                                    taskId === 'title-alignment-checker' ?
                                    '<li>Analyze syllabus schedule and module titles</li>' +
                                    '<li>Check for consistency and style compliance</li>' +
                                    '<li>Validate welcome message alignment</li>' +
                                    '<li>Identify title mismatches and style violations</li>' :
                                    taskId === 'assessment-date-updater' ?
                                    '<li>Scan assessment reminder wells for hard-coded dates</li>' +
                                    '<li>Parse syllabus for week-date mapping</li>' +
                                    '<li>Replace dates with week-based deadlines</li>' +
                                    '<li>Ensure consistency across all assessment reminders</li>' :
                                    taskId === 'table-caption-checker' ?
                                    '<li>Access ACU Online Design Library for standards</li>' +
                                    '<li>Analyze tables with class "acuo-table"</li>' +
                                    '<li>Check caption presence and styling compliance</li>' +
                                    '<li>Provide recommendations for accessibility</li>' :
                                    taskId === 'syllabus-acuo-attribution-remover' ?
                                    '<li>Analyze the course syllabus for "(ACU Online, YYYY)"</li>' +
                                    '<li>Classify occurrences into safe removals vs manual review</li>' +
                                    '<li>Provide risk assessment and excerpts for confidence</li>' +
                                    '<li>Execute only approved removals with hash-safety</li>' :
                                    '<li>Perform comprehensive analysis</li>' +
                                    '<li>Check for potential issues</li>' +
                                    '<li>Identify areas for improvement</li>' +
                                    '<li>Provide detailed recommendations</li>') +
                                '</ul>' +
                                '</div>' +
                                '<p><em>This analysis prioritizes safety and will never make changes without your explicit approval.</em></p>';
                            document.getElementById('analysisPreview').classList.add('active');
                            } else {
                                console.error('❌ Task not found in QA_TASKS:', taskId);
                                alert('Task not found: ' + taskId);
                            }
                        }
                    });
                    
                    // Add keyboard support
                    card.addEventListener('keydown', function(e) {
                        if (e.key === 'Enter' || e.key === ' ') {
                            e.preventDefault();
                            this.click();
                        }
                    });
                });
            }
            


            // Helper functions for enhanced reports
            function getEnhancedPriority(item) {
                if (item.severity === 'High' || item.reason?.includes('error') || item.reason?.includes('broken')) return 'High';
                if (item.severity === 'Medium' || item.reason?.includes('missing')) return 'Medium';
                return 'Low';
            }

            function getEnhancedRiskLevel(item) {
                if (item.reason?.includes('submissions') || item.reason?.includes('past due')) return 'High';
                if (item.reason?.includes('official') || item.reason?.includes('links')) return 'Medium';
                return 'Low';
            }

            function calculateEnhancedSuccessRate(result) {
                const successful = result.summary?.successful || 0;
                const failed = result.summary?.failed || 0;
                const total = successful + failed;
                return total > 0 ? Math.round((successful / total) * 100) : 0;
            }

            function generateEnhancedCanvasLink(item) {
                const canvasBaseUrl = 'https://aculeo.test.instructure.com'; // Use the known Canvas URL
                
                if (item.assignment_id) {
                    return \`\${canvasBaseUrl}/courses/\${courseId}/assignments/\${item.assignment_id}\`;
                } else if (item.delete_page_url || item.page_url) {
                    const pageUrl = item.delete_page_url || item.page_url;
                    return \`\${canvasBaseUrl}/courses/\${courseId}/pages/\${pageUrl}\`;
                } else if (item.page_id) {
                    return \`\${canvasBaseUrl}/courses/\${courseId}/pages/\${item.page_id}\`;
                } else {
                    return \`\${canvasBaseUrl}/courses/\${courseId}\`;
                }
            }
            
            return {
                startAnalysis,
                closePreview,
                proceedWithAnalysis,
                executeSelectedActions,
                downloadReport,
                downloadExecutionReport,
                runNewAnalysis,
                returnToTasks,
                toggleAll,
                initializeTaskCards
            };
        })();
        
        // Make QAApp available globally
        window.QAApp = QAApp;

        document.addEventListener('DOMContentLoaded', function() {
            QAApp.initializeTaskCards();
        });
    </script>
</body>
</html>
  `;
}

function groupTasksByCategory() {
  const grouped = {}
  Object.entries(QA_TASKS).forEach(([id, task]) => {
    if (!grouped[task.category]) grouped[task.category] = []
    grouped[task.category].push({ id, ...task })
  })
  return grouped
}

function getRealCourseId(token) {
  console.log('🔍 Full token context:', token.platformContext);
  console.log('🔍 Context ID:', token.platformContext?.context?.id);
  console.log('🔍 Alternative course ID:', token.platformContext?.custom?.canvas_course_id);
  console.log('🔍 All custom fields:', token.platformContext?.custom);
  console.log('🔍 Context object:', token.platformContext?.context);
  console.log('🔍 Platform context keys:', Object.keys(token.platformContext || {}));
  
  // Extract numeric course ID from endpoint URLs
  let numericCourseId = null;
  
  // Try to extract from lineitems URL
  const lineitemsUrl = token.platformContext?.endpoint?.lineitems;
  if (lineitemsUrl) {
    const match = lineitemsUrl.match(/\/courses\/(\d+)\//);
    if (match) {
      numericCourseId = match[1];
      console.log('🔍 Extracted numeric course ID from lineitems URL:', numericCourseId);
    }
  }
  
  // Try to extract from namesRoles URL
  const namesRolesUrl = token.platformContext?.namesRoles?.context_memberships_url;
  if (!numericCourseId && namesRolesUrl) {
    const match = namesRolesUrl.match(/\/courses\/(\d+)\//);
    if (match) {
      numericCourseId = match[1];
      console.log('🔍 Extracted numeric course ID from namesRoles URL:', numericCourseId);
    }
  }
  
  // Use numeric course ID if found, otherwise fall back to hash
  const courseId = numericCourseId || 
                   token.platformContext?.context?.id || 
                   token.platformContext?.custom?.canvas_course_id ||
                   token.platformContext?.custom?.course_id ||
                   token.platformContext?.context?.label ||
                   'unknown';
  
  console.log('🔍 Final selected course ID:', courseId);
  return courseId;
}

function getUserRole(token) {
  const roles = token.platformContext?.roles || []
  
  // Priority 1: Course-specific membership roles (mapped to Canvas People tab display names)
  if (roles.some(role => role.includes('membership#Instructor'))) return 'Editing Lecturer'
  if (roles.some(role => role.includes('membership#ContentDeveloper'))) return 'Designer'
  if (roles.some(role => role.includes('membership#TeachingAssistant') || role.includes('membership#TA'))) return 'TA'
  if (roles.some(role => role.includes('membership#Student'))) return 'Student'
  if (roles.some(role => role.includes('membership#Administrator'))) return 'Administrator'
  
  // Priority 2: Institution-wide roles (mapped to Canvas display names)
  if (roles.some(role => role.includes('institution') && role.includes('Instructor'))) return 'Editing Lecturer'
  if (roles.some(role => role.includes('institution') && role.includes('TeachingAssistant'))) return 'TA'
  if (roles.some(role => role.includes('institution') && role.includes('Student'))) return 'Student'
  if (roles.some(role => role.includes('institution') && role.includes('Administrator'))) return 'Administrator'
  
  // Priority 3: Generic role fallback (mapped to Canvas display names)
  if (roles.some(role => role.includes('Instructor'))) return 'Editing Lecturer'
  if (roles.some(role => role.includes('Student'))) return 'Student'
  
  return 'User'
}

async function getRealUserName(token) {
  // Priority order: LTI userInfo display name, constructed full name, then fallbacks
  
  // First priority: Use LTI userInfo.name (contains full display name like "Anwar BinUmer")
  if (token.userInfo?.name) {
    return token.userInfo.name;
  }
  
  // Second priority: Construct from userInfo given_name + family_name
  if (token.userInfo?.given_name || token.userInfo?.family_name) {
    const fullName = [token.userInfo.given_name, token.userInfo.family_name].filter(n => n).join(' ');
    if (fullName) return fullName;
  }
  
  // Fallback to other token fields
  const legacyFullName = [token.given_name, token.family_name].filter(n => n).join(' ');
  const emailName = token.email ? token.email.split('@')[0] : null;
  
  return legacyFullName || 
         token.name || 
         token.nickname ||
         token.preferred_username ||
         emailName ||
         token.platformContext?.lis?.person_sourcedid || 
         'User';
}

// LTI Platform Setup
const setup = async () => {
  try {
    // Deploy the LTI provider first
    await lti.deploy({ port: process.env.PORT || 8080 })
    console.log('🚀 QA Automation LTI Server running on port', process.env.PORT || 8080)
    console.log('🔗 Tunnel URL: https://pgp-blond-blink-pics.trycloudflare.com')
    console.log('📝 Update Canvas Developer Key with: https://pgp-blond-blink-pics.trycloudflare.com')
    
    // Then register the platform
    await lti.registerPlatform({
      url: 'https://canvas.test.instructure.com',
      name: 'Canvas Test',
      clientId: process.env.CANVAS_CLIENT_ID || 'your_client_id',
      authenticationEndpoint: 'https://canvas.test.instructure.com/api/lti/authorize_redirect',
      accesstokenEndpoint: 'https://canvas.test.instructure.com/login/oauth2/token',
      authConfig: { method: 'JWK_SET', key: 'https://canvas.test.instructure.com/api/lti/security/jwks' }
    })
    console.log('✅ Canvas platform registered successfully')
  } catch (err) {
    console.error('❌ Failed to start LTI server:', err)
    process.exit(1)
  }
}

setup()

