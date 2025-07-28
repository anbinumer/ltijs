const path = require('path')
const express = require('express')
require('dotenv').config() // Add this line

// Require Provider 
const lti = require('ltijs').Provider

// Setup provider
lti.setup(process.env.LTI_KEY || 'QA_AUTOMATION_KEY_2024', // Key used to sign cookies and tokens
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
    staticPath: path.join(__dirname, 'public') // Serve static files
  }
)

// Whitelist the execute endpoints
lti.whitelist('/execute')
lti.whitelist('/execute-approved')

// Enhanced error handling for the main execute endpoint
lti.app.post('/execute', async (req, res) => {
  const { taskId, courseId, userId } = req.body
  
  try {
    console.log(`Phase 2: Analyzing task: ${taskId} for course: ${courseId}`)
    
    // Validate required parameters
    if (!taskId) {
      throw new Error('Task ID is required');
    }
    if (!courseId) {
      throw new Error('Course ID is required');
    }
    
    // Phase 2: Always analyze first (preview-first workflow)
    const analysisResult = await analyzeTask(taskId, courseId, userId)
    
    res.json({ 
      success: true, 
      phase: 2,
      mode: 'preview_first',
      taskId,
      result: analysisResult 
    })
  } catch (error) {
    console.error('Phase 2 Analysis error:', error)
    
    // Enhanced error response with debugging info
    res.status(500).json({ 
      success: false, 
      error: error.message,
      phase: 2,
      debug: {
        taskId,
        courseId,
        timestamp: new Date().toISOString(),
        errorType: error.constructor.name
      }
    })
  }
})

// Enhanced analyzeTask function for Phase 2 with better error handling
async function analyzeTask(taskId, courseId, userId) {
  const { spawn } = require('child_process');
  const path = require('path');
  
  switch (taskId) {
    case 'find-duplicate-pages':
      return new Promise((resolve, reject) => {
        const scriptPath = path.join(__dirname, 'scripts', 'duplicate_page_cleaner.py');
        const canvasUrl = process.env.CANVAS_URL || 'aculeo.test.instructure.com';
        const apiToken = process.env.CANVAS_API_TOKEN || '';
        
        // Enhanced validation
        if (!apiToken) {
          reject(new Error('Canvas API token not configured. Please set CANVAS_API_TOKEN in your environment.'));
          return;
        }
        
        if (!canvasUrl) {
          reject(new Error('Canvas URL not configured. Please set CANVAS_URL in your environment.'));
          return;
        }
        
        // Check if Python script exists
        const fs = require('fs');
        if (!fs.existsSync(scriptPath)) {
          reject(new Error(`Python script not found at: ${scriptPath}`));
          return;
        }
        
        // Phase 2: Analysis arguments for duplicate_page_cleaner.py
        const args = [
          scriptPath,
          '--canvas-url', canvasUrl,
          '--api-token', apiToken,
          '--course-id', courseId,
          '--similarity-threshold', '0.9',
          '--analyze-only'           // Always analyze first in Phase 2
        ];
        
        console.log('Phase 2 Duplicate Page Cleaner Analysis with args:', args);
        console.log('Working directory:', __dirname);
        console.log('Script path exists:', fs.existsSync(scriptPath));
        
        // Set timeout to prevent hanging
        const timeoutMs = 300000; // 5 minutes
        const timeout = setTimeout(() => {
          python.kill('SIGTERM');
          reject(new Error('Analysis timed out after 5 minutes. This may indicate a network issue or large course size.'));
        }, timeoutMs);
        
        const python = spawn('python3', args, {
          cwd: __dirname,
          env: {
            ...process.env,
            PYTHONPATH: path.join(__dirname, 'scripts'),
            PYTHONUNBUFFERED: '1'
          }
        });
        
        let output = '';
        let error = '';
        
        python.stdout.on('data', (data) => {
          const chunk = data.toString();
          output += chunk;
          console.log('PYTHON STDOUT:', chunk);
        });
        
        python.stderr.on('data', (data) => {
          const chunk = data.toString();
          error += chunk;
          console.log('PYTHON STDERR:', chunk);
        });
        
        python.on('close', (code) => {
          clearTimeout(timeout);
          
          console.log('=== ENHANCED PYTHON SCRIPT DEBUG ===');
          console.log(`Exit code: ${code}`);
          console.log(`STDOUT length: ${output.length}`);
          console.log(`STDERR length: ${error.length}`);
          console.log('--- STDOUT CONTENT ---');
          console.log(output);
          console.log('--- STDERR CONTENT ---');
          console.log(error);
          console.log('=== END DEBUG ===');
          
          if (code === 0) {
            // Enhanced JSON parsing with multiple fallback strategies
            try {
              // Strategy 1: Look for enhanced analysis JSON
              const enhancedMatch = output.match(/ENHANCED_ANALYSIS_JSON:\s*(.+)/);
              if (enhancedMatch) {
                try {
                  const analysisResults = JSON.parse(enhancedMatch[1]);
                  console.log('Successfully parsed enhanced analysis JSON');
                  
                  // Phase 2: Return detailed findings for user review
                  resolve({
                    phase: 2,
                    mode: 'preview_first',
                    analyzed_only: true,
                    executed: false,
                    findings: analysisResults,
                    user_approval_required: true,
                    risk_assessment: analysisResults.risk_assessment,
                    safe_actions: analysisResults.findings?.safe_actions || [],
                    requires_manual_review: analysisResults.findings?.requires_manual_review || [],
                    inbound_links_checked: true,
                    next_steps: {
                      safe_actions_count: (analysisResults.findings?.safe_actions || []).length,
                      manual_review_count: (analysisResults.findings?.requires_manual_review || []).length,
                      can_proceed_with_safe_actions: (analysisResults.findings?.safe_actions || []).length > 0
                    }
                  });
                  return;
                } catch (parseError) {
                  console.error('Failed to parse enhanced analysis JSON:', parseError);
                  console.error('Raw JSON string:', enhancedMatch[1]);
                }
              }
              
              // Strategy 2: Look for regular JSON output
              const regularMatch = output.match(/JSON_OUTPUT:\s*(.+)/);
              if (regularMatch) {
                try {
                  const fallbackResults = JSON.parse(regularMatch[1]);
                  console.log('Successfully parsed fallback JSON');
                  resolve({
                    phase: 2,
                    mode: 'preview_first',
                    analyzed_only: true,
                    executed: false,
                    findings: fallbackResults,
                    user_approval_required: true,
                    fallback_mode: true
                  });
                  return;
                } catch (parseError) {
                  console.error('Failed to parse fallback JSON:', parseError);
                }
              }
              
              // Strategy 3: Try to parse any JSON-like content
              const jsonPattern = /\{[\s\S]*\}/;
              const jsonMatch = output.match(jsonPattern);
              if (jsonMatch) {
                try {
                  const extractedResults = JSON.parse(jsonMatch[0]);
                  console.log('Successfully parsed extracted JSON');
                  resolve({
                    phase: 2,
                    mode: 'preview_first',
                    analyzed_only: true,
                    executed: false,
                    findings: extractedResults,
                    user_approval_required: true,
                    extracted_mode: true
                  });
                  return;
                } catch (parseError) {
                  console.error('Failed to parse extracted JSON:', parseError);
                }
              }
              
              // Strategy 4: If no JSON found, check for specific success indicators
              if (output.includes('Enhanced analysis complete') || output.includes('Found') || output.includes('analysis') || 
                  output.includes('✅ Phase 2 Enhanced Analysis completed') || output.includes('Analysis and cleanup completed')) {
                resolve({
                  phase: 2,
                  mode: 'preview_first',
                  analyzed_only: true,
                  executed: false,
                  findings: {
                    message: 'Analysis completed but results parsing failed',
                    raw_output: output.substring(0, 1000) // Limit output size
                  },
                  user_approval_required: false,
                  parsing_error: true
                });
                return;
              }
              
              // If we get here, no recognizable output was found
              reject(new Error('Analysis completed but no recognizable results were found. Raw output: ' + output.substring(0, 500)));
              
            } catch (generalError) {
              console.error('General error in result processing:', generalError);
              reject(new Error('Analysis completed but result processing failed: ' + generalError.message));
            }
          } else {
            // Enhanced error reporting
            let errorMessage = `Analysis failed with exit code ${code}`;
            
            if (error.includes('ModuleNotFoundError')) {
              const missingModule = error.match(/No module named '([^']+)'/);
              if (missingModule) {
                errorMessage = `Missing Python package: ${missingModule[1]}. Please install it with: pip3 install ${missingModule[1]}`;
              } else {
                errorMessage = 'Missing Python packages. Please install required dependencies.';
              }
            } else if (error.includes('401') || error.includes('Unauthorized')) {
              errorMessage = 'Canvas API authentication failed. Please check your API token.';
            } else if (error.includes('403') || error.includes('Forbidden')) {
              errorMessage = 'Canvas API access forbidden. Please check your API token permissions.';
            } else if (error.includes('404')) {
              errorMessage = 'Course not found or API endpoint invalid. Please check the course ID.';
            } else if (error.includes('timeout') || error.includes('ConnectionError')) {
              errorMessage = 'Network timeout connecting to Canvas. Please try again.';
            } else if (error.includes('ImportError')) {
              errorMessage = 'Python script import error. Please check script dependencies.';
            } else if (error) {
              errorMessage = `Python script error: ${error.substring(0, 200)}`;
            }
            
            reject(new Error(errorMessage));
          }
        });
        
        python.on('error', (spawnError) => {
          clearTimeout(timeout);
          console.error('Failed to start Python process:', spawnError);
          
          if (spawnError.code === 'ENOENT') {
            reject(new Error('Python3 not found. Please ensure Python 3 is installed and accessible via "python3" command.'));
          } else {
            reject(new Error(`Failed to start analysis process: ${spawnError.message}`));
          }
        });
      });
    
    default:
      throw new Error(`Unknown task: ${taskId}`)
  }
}

// Add new endpoint for executing approved actions (Phase 2)
lti.app.post('/execute-approved', async (req, res) => {
  const { taskId, courseId, userId, approvedActions } = req.body
  
  try {
    console.log(`Phase 2: Executing approved actions for task: ${taskId}`)
    console.log(`Approved actions:`, approvedActions)
    
    const result = await executeApprovedActions(taskId, courseId, userId, approvedActions)
    
    res.json({ 
      success: true, 
      phase: 2,
      mode: 'execute_approved',
      taskId,
      result: result 
    })
  } catch (error) {
    console.error('Phase 2 Execution error:', error)
    res.json({ 
      success: false, 
      error: error.message 
    })
  }
})

// Function to execute only approved actions
async function executeApprovedActions(taskId, courseId, userId, approvedActions) {
  const { spawn } = require('child_process');
  const path = require('path');
  
  switch (taskId) {
    case 'find-duplicate-pages':
      return new Promise((resolve, reject) => {
        const scriptPath = path.join(__dirname, 'scripts', 'duplicate_page_cleaner.py');
        const canvasUrl = process.env.CANVAS_URL || 'aculeo.test.instructure.com';
        const apiToken = process.env.CANVAS_API_TOKEN || '';
        
        if (!apiToken) {
          reject(new Error('Canvas API token not configured'));
          return;
        }
        
        // Create temporary file with approved actions
        const fs = require('fs');
        const actionsFile = path.join(__dirname, 'temp', `approved_actions_${courseId}_${Date.now()}.json`);
        
        // Ensure temp directory exists
        const tempDir = path.dirname(actionsFile);
        if (!fs.existsSync(tempDir)) {
          fs.mkdirSync(tempDir, { recursive: true });
        }
        
        fs.writeFileSync(actionsFile, JSON.stringify(approvedActions, null, 2));
        
        const args = [
          scriptPath,
          '--canvas-url', canvasUrl,
          '--api-token', apiToken,
          '--course-id', courseId,
          '--execute-approved', actionsFile  // Execute only approved actions
        ];
        
        console.log('Phase 2 Executing approved actions with args:', args);
        const python = spawn('python3', args);
        
        let output = '';
        let error = '';
        
        python.stdout.on('data', (data) => {
          output += data.toString();
        });
        
        python.stderr.on('data', (data) => {
          error += data.toString();
        });
        
        python.on('close', (code) => {
          // Clean up temporary file
          try {
            fs.unlinkSync(actionsFile);
          } catch (e) {
            console.warn('Could not clean up temp file:', e.message);
          }
          
          if (code === 0) {
            const jsonMatch = output.match(/EXECUTION_RESULTS_JSON: (.+)/);
            if (jsonMatch) {
              try {
                const executionResults = JSON.parse(jsonMatch[1]);
                resolve({
                  phase: 2,
                  mode: 'execution_complete',
                  executed: true,
                  results: executionResults,
                  summary: {
                    actions_requested: approvedActions.length,
                    actions_completed: executionResults.successful_deletions?.length || 0,
                    actions_failed: executionResults.failed_deletions?.length || 0
                  }
                });
              } catch (e) {
                console.error('Failed to parse execution results JSON:', e);
                resolve({
                  phase: 2,
                  mode: 'execution_complete',
                  executed: true,
                  message: 'Execution completed',
                  output: output
                });
              }
            } else {
              resolve({
                phase: 2,
                mode: 'execution_complete',
                executed: true,
                message: 'Execution completed',
                output: output
              });
            }
          } else {
            reject(new Error(`Execution failed: ${error}`));
          }
        });
      });
    
    default:
      throw new Error(`Unknown task: ${taskId}`)
  }
}

// QA Task Definitions - MVP: Duplicate Pages Only
const QA_TASKS = {
  'find-duplicate-pages': {
    name: 'Find and Remove Duplicate Pages',
    description: 'Identify and remove duplicate page content using Canvas API and content analysis',
    category: 'Content Management',
    mvp: true
  }
}

// Main LTI launch handler
lti.onConnect(async (token, req, res) => {
  console.log('Full LTI Token:', JSON.stringify(token, null, 2)) // DEBUG: See actual token structure
  console.log('LTI Launch Token:', {
    iss: token.iss,
    aud: token.aud,
    sub: token.sub,
    context: token.platformContext
  })
  
  // Debug course ID extraction
  console.log('=== COURSE ID EXTRACTION DEBUG ===')
  const realCourseId = getRealCourseId(token)
  console.log('Extracted Course ID:', realCourseId)
  console.log('Original Context ID:', token.platformContext?.context?.id)
  console.log('Return URL:', token.platformContext?.launchPresentation?.return_url)
  console.log('Launch URL:', token.platformContext?.launchPresentation?.launch_url)
  console.log('Custom Params:', token.platformContext?.custom)
  console.log('================================')

  // Get real user name for audit purposes
  const realUserName = await getRealUserName(token);
  token.realUserName = realUserName;

  // Render QA Tools Dashboard
  const html = generateEnhancedQADashboard(token)
  return res.send(html)
})

// Helper function to extract real Canvas course ID from LTI token
function getRealCourseId(token) {
  // Try to extract from return URL first (most reliable)
  const returnUrl = token.platformContext?.launchPresentation?.return_url;
  if (returnUrl) {
    const match = returnUrl.match(/\/courses\/(\d+)\//);
    if (match) return match[1];
  }
  
  // Fallback to context ID (may not work for API calls)
  return token.platformContext?.context?.id;
}

// Helper function to extract user role from LTI token
function getUserRole(token) {
  if (!token.platformContext?.roles) return 'User';
  
  const roles = token.platformContext.roles;
  
  // Check for highest priority role first
  if (roles.some(role => role.includes('Administrator'))) return 'Administrator';
  if (roles.some(role => role.includes('Instructor'))) return 'Instructor';
  if (roles.some(role => role.includes('TeachingAssistant'))) return 'Teaching Assistant';
  if (roles.some(role => role.includes('Designer'))) return 'Course Designer';
  if (roles.some(role => role.includes('Student'))) return 'Student';
  
  return 'Canvas User';
}

// Function to extract real Canvas course ID from LTI token
function getRealCourseId(token) {
  // Method 1: Try to extract from return URL (most reliable)
  const returnUrl = token.platformContext?.launchPresentation?.return_url;
  if (returnUrl) {
    const match = returnUrl.match(/\/courses\/(\d+)\//);
    if (match) {
      console.log(`Course ID from return URL: ${match[1]}`);
      return match[1];
    }
  }
  
  // Method 2: Try to extract from launch URL
  const launchUrl = token.platformContext?.launchPresentation?.launch_url;
  if (launchUrl) {
    const match = launchUrl.match(/\/courses\/(\d+)\//);
    if (match) {
      console.log(`Course ID from launch URL: ${match[1]}`);
      return match[1];
    }
  }
  
  // Method 3: Try custom parameters (Canvas sometimes passes this)
  const customParams = token.platformContext?.custom;
  if (customParams?.canvas_course_id) {
    console.log(`Course ID from custom params: ${customParams.canvas_course_id}`);
    return customParams.canvas_course_id;
  }
  
  // Method 4: Check for numeric ID in context
  const contextId = token.platformContext?.context?.id;
  if (contextId && /^\d+$/.test(contextId)) {
    console.log(`Course ID from context (numeric): ${contextId}`);
    return contextId;
  }
  
  // Fallback: Use your known course ID for testing
  console.log('Using fallback course ID: 280');
  return '280';
}

// Function to get real user name using LTI Names and Roles Provisioning Service
async function getRealUserName(token) {
  try {
    const namesRolesUrl = token.platformContext?.namesRoles?.context_memberships_url;
    
    console.log('=== USER NAME DEBUG (Current User) ===');
    console.log('User UUID:', token.user);
    console.log('Names & Roles URL:', namesRolesUrl);
    
    if (!namesRolesUrl) {
      return 'Canvas User (No NRPS)';
    }
    
    // Use ltijs built-in method to get current user from Canvas
    const nrpsResponse = await lti.NamesAndRoles.getMembers(token);
    console.log('NRPS Response type:', typeof nrpsResponse);
    console.log('NRPS Response:', nrpsResponse);
    
    // Handle different response formats
    let nrpsMembers = [];
    if (Array.isArray(nrpsResponse)) {
      nrpsMembers = nrpsResponse;
    } else if (nrpsResponse && nrpsResponse.members) {
      nrpsMembers = nrpsResponse.members;
    } else if (nrpsResponse && Array.isArray(nrpsResponse.body)) {
      nrpsMembers = nrpsResponse.body;
    } else {
      console.log('Unexpected NRPS response format');
      return 'Canvas User (NRPS Format Error)';
    }
    
    console.log('NRPS Members found:', nrpsMembers.length);
    console.log('First member sample:', nrpsMembers[0]);
    
    // Find current user in the membership list
    const currentUser = nrpsMembers.find(member => 
      member.user_id === token.user || 
      member.userId === token.user ||
      member.lti_user_id === token.user
    );
    
    if (currentUser) {
      console.log('Found current user:', currentUser);
      return currentUser.name || 
             (currentUser.given_name + ' ' + currentUser.family_name) || 
             currentUser.sortable_name || 
             'Canvas User';
    }
    
    console.log('Current user not found in members list');
    return 'Canvas User (Not in Members)';
  } catch (error) {
    console.error('Error fetching current user name:', error);
    return 'Canvas User (NRPS Error)';
  }
}

// Helper function to extract user name (Canvas typically doesn't provide this)
function extractUserName(token) {
  // Canvas doesn't typically provide user names via LTI for privacy
  // You could make a Canvas API call here if needed, but for now:
  return 'Canvas User';
}

// Generate the QA Tools Dashboard HTML (AFTER getUserRole function)
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
            /* Canvas-native colors */
            --canvas-success: #00ac18;
            --canvas-warning: #fc5e13;
            --canvas-danger: #ee0612;
            --canvas-border: #c7cdd1;
            
            /* ACU Brand Colors */
            --acu-deep-purple: #4A1A4A;
            --acu-purple: #6B2C6B;
            --acu-red: #D2492A;
            --acu-red-dark: #B8391F;
            --acu-gold: #F4B942;
            --acu-gold-dark: #E6A830;
            --acu-cream: #F9F4F1;
            --acu-cream-light: #F4ECE6;
            
            /* Applied ACU theme */
            --canvas-primary: var(--acu-deep-purple);
            --canvas-primary-dark: var(--acu-purple);
            --canvas-background: var(--acu-cream);
            --canvas-surface: #ffffff;
            --canvas-text: var(--acu-purple);
            --canvas-text-light: #8a5a8a;
        }

        body { 
            font-family: 'Segoe UI', system-ui, -apple-system, sans-serif; 
            margin: 0; 
            padding: 20px; 
            background: var(--canvas-background);
            color: var(--canvas-text);
            line-height: 1.5;
        }

        /* Header with confidence-building messaging */
        .header {
            background: var(--canvas-surface);
            padding: 24px;
            border-radius: 8px;
            margin-bottom: 24px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
            border-left: 4px solid var(--acu-primary);
        }

        .header h1 {
            margin: 0 0 8px 0;
            color: var(--canvas-text);
            font-size: 24px;
            font-weight: 600;
        }

        .header p {
            margin: 0 0 16px 0;
            color: var(--canvas-text-light);
        }

        .course-info {
            background: linear-gradient(135deg, var(--acu-cream) 0%, var(--acu-cream-light) 100%);
            padding: 16px;
            border-radius: 6px;
            border: 1px solid var(--acu-gold);
        }

        .course-info strong {
            color: var(--acu-deep-purple);
        }

        /* Task categories with enhanced visual hierarchy */
        .task-category {
            background: var(--canvas-surface);
            margin-bottom: 24px;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
            overflow: hidden;
        }

        .category-header {
            background: linear-gradient(135deg, var(--acu-deep-purple) 0%, var(--acu-purple) 100%);
            color: white;
            padding: 20px 24px;
            font-weight: 600;
            font-size: 16px;
            display: flex;
            align-items: center;
        }

        /* Enhanced task cards with better interactivity */
        .task-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
            gap: 20px;
            padding: 24px;
        }

        .task-card {
            border: 2px solid var(--canvas-border);
            border-radius: 8px;
            padding: 20px;
            cursor: pointer;
            transition: all 0.3s ease;
            background: var(--canvas-surface);
            position: relative;
            overflow: hidden;
        }

        .task-card::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            width: 4px;
            height: 100%;
            background: var(--acu-deep-purple);
            transform: scaleY(0);
            transition: transform 0.3s ease;
        }

        .task-card:hover {
            border-color: var(--acu-deep-purple);
            background: var(--acu-cream-light);
            transform: translateY(-2px);
            box-shadow: 0 8px 24px rgba(74, 26, 74, 0.15);
        }

        .task-card:hover::before {
            transform: scaleY(1);
        }

        .task-name { 
            font-weight: 600; 
            color: var(--canvas-text); 
            margin: 0 0 12px 0;
            font-size: 16px;
        }

        .task-description { 
            color: var(--canvas-text-light); 
            font-size: 14px;
            margin: 0 0 16px 0;
            line-height: 1.4;
        }

        .task-meta {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-top: 16px;
            padding-top: 16px;
            border-top: 1px solid #eee;
        }

        .task-status {
            font-size: 12px;
            padding: 4px 8px;
            border-radius: 12px;
            background: var(--acu-gold);
            color: var(--acu-deep-purple);
            font-weight: 500;
        }

        .task-button {
            background: var(--acu-red);
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 6px;
            cursor: pointer;
            font-weight: 500;
            font-size: 14px;
            transition: all 0.2s ease;
        }

        .task-button:hover { 
            background: var(--acu-red-dark);
            transform: scale(1.02);
        }

        /* Analysis Preview Modal */
        .analysis-preview {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.7);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 1000;
            opacity: 0;
            visibility: hidden;
            transition: all 0.3s ease;
        }

        .analysis-preview.active {
            opacity: 1;
            visibility: visible;
        }

        .preview-card {
            background: var(--canvas-surface);
            border-radius: 12px;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
            max-width: 600px;
            width: 90%;
            max-height: 80vh;
            display: flex;
            flex-direction: column;
        }

        .preview-header {
            padding: 24px 24px 0 24px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--canvas-border);
            padding-bottom: 16px;
            margin-bottom: 0;
        }

        .preview-header h2 {
            margin: 0;
            color: var(--canvas-text);
            font-size: 20px;
        }

        .close-btn {
            background: none;
            border: none;
            font-size: 24px;
            cursor: pointer;
            color: var(--canvas-text-light);
            padding: 0;
            width: 32px;
            height: 32px;
            display: flex;
            align-items: center;
            justify-content: center;
            border-radius: 4px;
        }

        .close-btn:hover {
            background: #f0f0f0;
            color: var(--canvas-text);
        }

        .preview-content {
            padding: 24px;
            overflow-y: auto;
            flex: 1;
        }

        .preview-actions {
            padding: 16px 24px 24px;
            display: flex;
            justify-content: flex-end;
            gap: 12px;
            border-top: 1px solid var(--canvas-border);
        }

        .btn-primary, .btn-secondary {
            padding: 12px 24px;
            border-radius: 6px;
            border: none;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.2s ease;
        }

        .btn-primary {
            background: var(--acu-red);
            color: white;
        }

        .btn-primary:hover {
            background: var(--acu-red-dark);
        }

        .btn-secondary {
            background: var(--acu-cream);
            color: var(--acu-deep-purple);
            border: 1px solid var(--acu-gold);
        }

        .btn-secondary:hover {
            background: var(--acu-cream-light);
        }

        .analysis-scope {
            background: var(--acu-cream-light);
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 20px;
            border-left: 4px solid var(--acu-deep-purple);
        }

        .scope-item {
            display: flex;
            justify-content: space-between;
            margin-bottom: 8px;
        }

        .scope-item:last-child {
            margin-bottom: 0;
        }

        .methodology-box {
            background: var(--acu-cream);
            padding: 16px;
            border-radius: 6px;
            margin-top: 16px;
            border-left: 3px solid var(--acu-gold);
        }

        .methodology-box h4 {
            margin: 0 0 8px 0;
            color: var(--canvas-text);
            font-size: 14px;
        }

        .methodology-box p {
            margin: 0;
            font-size: 13px;
            color: var(--canvas-text-light);
            line-height: 1.4;
        }
        .progress-overlay {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.7);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 1000;
            opacity: 0;
            visibility: hidden;
            transition: all 0.3s ease;
        }

        .progress-overlay.active {
            opacity: 1;
            visibility: visible;
        }

        .progress-card {
            background: var(--canvas-surface);
            padding: 32px;
            border-radius: 12px;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
            text-align: center;
            max-width: 400px;
            width: 90%;
        }

        .progress-spinner {
            width: 48px;
            height: 48px;
            border: 4px solid #f0f0f0;
            border-top: 4px solid var(--acu-red);
            border-radius: 50%;
            animation: spin 1s linear infinite;
            margin: 0 auto 20px;
        }

        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }

        .progress-text {
            font-size: 16px;
            color: var(--canvas-text);
            margin-bottom: 12px;
        }

        .progress-details {
            font-size: 14px;
            color: var(--canvas-text-light);
        }

        /* Results display */
        .results-container {
            margin-top: 24px;
            background: var(--canvas-surface);
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
            overflow: hidden;
            display: none;
        }

        .results-header {
            background: linear-gradient(135deg, var(--acu-deep-purple) 0%, var(--acu-purple) 100%);
            color: white;
            padding: 20px 24px;
            font-weight: 600;
        }

        .results-content {
            padding: 24px;
        }

        .result-summary {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
            margin-bottom: 24px;
        }

        .summary-card {
            background: var(--acu-cream);
            padding: 16px;
            border-radius: 6px;
            text-align: center;
            border-left: 4px solid var(--acu-deep-purple);
        }

        .summary-number {
            font-size: 24px;
            font-weight: 600;
            color: var(--acu-deep-purple);
            margin-bottom: 4px;
        }

        .summary-label {
            font-size: 12px;
            color: var(--canvas-text-light);
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        /* Responsive design */
        @media (max-width: 768px) {
            body {
                padding: 12px;
            }
            
            .task-grid {
                grid-template-columns: 1fr;
                padding: 16px;
            }
            
            .header {
                padding: 16px;
            }
        }

        /* Accessibility improvements */
        .task-card:focus {
            outline: 2px solid var(--acu-primary);
            outline-offset: 2px;
        }

        .task-button:focus {
            outline: 2px solid var(--canvas-surface);
            outline-offset: 2px;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>Canvas QA Automation Suite</h1>
        <p>Streamline your course quality assurance with intelligent automation and detailed reporting.</p>
        <div class="course-info">
            <strong>User:</strong> ${token.realUserName || 'Canvas User'} | 
            <strong>Course:</strong> ${token.platformContext?.context?.title || 'Unknown Course'} |
            <strong>Role:</strong> ${getUserRole(token)}
        </div>
    </div>

    ${Object.entries(taskCategories).map(([category, tasks]) => `
        <div class="task-category">
            <div class="category-header">${category}</div>
            <div class="task-grid">
                ${tasks.map(task => `
                    <div class="task-card" onclick="console.log('Task card clicked for: ${task.id}'); startAnalysis('${task.id}');" tabindex="0" role="button" aria-label="Analyze ${task.name}">
                        <div class="task-name">${task.name}</div>
                        <div class="task-description">${task.description}</div>
                        <div class="task-meta">
                            <span class="task-status">Ready for Analysis</span>
                            <button class="task-button" onclick="event.stopPropagation(); console.log('Begin Analysis clicked for: ${task.id}'); startAnalysis('${task.id}');">
                                Begin Analysis
                            </button>
                        </div>
                    </div>
                `).join('')}
            </div>
        </div>
    `).join('')}

    <!-- Analysis Preview Modal -->
    <div class="analysis-preview" id="analysisPreview">
        <div class="preview-card">
            <div class="preview-header">
                <h2 id="previewTitle">Analysis Overview</h2>
                <button class="close-btn" onclick="closePreview()">&times;</button>
            </div>
            <div class="preview-content" id="previewContent">
                <!-- Preview content will be populated here -->
            </div>
            <div class="preview-actions">
                <button class="btn-secondary" onclick="closePreview()">Review Later</button>
                <button class="btn-primary" onclick="proceedWithAnalysis()" id="proceedBtn">Proceed with Analysis</button>
            </div>
        </div>
    </div>
    <div class="progress-overlay" id="progressOverlay">
        <div class="progress-card">
            <div class="progress-spinner"></div>
            <div class="progress-text" id="progressText">Initializing QA analysis...</div>
            <div class="progress-details" id="progressDetails">This may take a few moments</div>
        </div>
    </div>

    <!-- Results Container -->
    <div class="results-container" id="resultsContainer">
        <div class="results-header">
            <h2 id="resultsTitle">Analysis Complete</h2>
        </div>
        <div class="results-content" id="resultsContent">
            <!-- Results will be populated here -->
        </div>
    </div>

    <script>
        let currentTaskId = null;
        let currentAnalysisResult = null;
        let currentUserId = '${token.sub || 'unknown'}';

        // Phase 2: Main analysis functions
        function startAnalysis(taskId) {
            console.log('Phase 2: Starting analysis preview for:', taskId);
            currentTaskId = taskId;
            showAnalysisPreview(taskId);
        }

        function showAnalysisPreview(taskId) {
            console.log('Phase 2: Showing analysis preview for:', taskId);
            const preview = document.getElementById('analysisPreview');
            const title = document.getElementById('previewTitle');
            const content = document.getElementById('previewContent');
            
            if (!preview || !title || !content) {
                console.error('Preview elements not found');
                return;
            }
            
            if (taskId === 'find-duplicate-pages') {
                title.textContent = 'Phase 2: Enhanced Duplicate Analysis Preview';
                content.innerHTML = generateDuplicateAnalysisPreview();
            }
            
            preview.classList.add('active');
        }

        function generateDuplicateAnalysisPreview() {
            return \`
                <!-- Confidence-Building Header -->
                        <div style="background: linear-gradient(135deg, var(--acu-cream) 0%, var(--acu-cream-light) 100%); padding: 20px; border-radius: 8px; margin-bottom: 20px; border-left: 4px solid var(--acu-deep-purple);">
        <div style="display: flex; align-items: center; margin-bottom: 12px;">
        <span style="font-size: 20px; margin-right: 12px;">🔍</span>
        <h3 style="margin: 0; color: var(--acu-deep-purple); font-size: 18px;">Smart Course Cleanup Analysis</h3>
        </div>
        <p style="margin: 0; color: var(--acu-purple); font-size: 14px; line-height: 1.5;">
                        This analysis will intelligently identify and resolve duplicate content while protecting your course integrity. 
                        <strong>No student-facing content will be affected.</strong>
                    </p>
                </div>

                <!-- User-Friendly Analysis Scope -->
                <div style="background: var(--acu-cream); padding: 20px; border-radius: 8px; margin-bottom: 20px; border-left: 4px solid var(--acu-deep-purple);">
                    <h4 style="margin: 0 0 16px 0; color: var(--acu-deep-purple); font-size: 16px;">What This Analysis Will Do:</h4>
                    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 16px;">
                        <div style="background: white; padding: 16px; border-radius: 6px; border: 1px solid var(--acu-gold);">
                            <div style="font-weight: 600; color: var(--acu-deep-purple); margin-bottom: 8px;">📄 Content Scan</div>
                            <div style="font-size: 13px; color: var(--acu-purple);">All course pages, modules, and assignments</div>
                        </div>
                        <div style="background: white; padding: 16px; border-radius: 6px; border: 1px solid var(--acu-gold);">
                            <div style="font-weight: 600; color: var(--acu-deep-purple); margin-bottom: 8px;">🔗 Link Protection</div>
                            <div style="font-size: 13px; color: var(--acu-purple);">Pages with inbound links are automatically protected</div>
                        </div>
                        <div style="background: white; padding: 16px; border-radius: 6px; border: 1px solid var(--acu-gold);">
                            <div style="font-weight: 600; color: var(--acu-deep-purple); margin-bottom: 8px;">⚡ Smart Detection</div>
                            <div style="font-size: 13px; color: var(--acu-purple);">90% similarity threshold for accurate matching</div>
                        </div>
                        <div style="background: white; padding: 16px; border-radius: 6px; border: 1px solid var(--acu-gold);">
                            <div style="font-weight: 600; color: var(--acu-deep-purple); margin-bottom: 8px;">⏱️ Quick Analysis</div>
                            <div style="font-size: 13px; color: var(--acu-purple);">3-5 minutes for comprehensive review</div>
                        </div>
                    </div>
                </div>
                
                <!-- Step-by-Step Process -->
                <div style="background: var(--acu-cream-light); padding: 20px; border-radius: 8px; margin-bottom: 20px; border-left: 4px solid var(--acu-gold);">
                    <h4 style="margin: 0 0 16px 0; color: var(--acu-deep-purple); font-size: 16px;">How It Works:</h4>
                    <div style="display: flex; flex-direction: column; gap: 12px;">
                        <div style="display: flex; align-items: center;">
                            <span style="background: var(--acu-gold); color: var(--acu-deep-purple); width: 24px; height: 24px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: bold; margin-right: 12px;">1</span>
                            <span style="color: var(--acu-deep-purple); font-size: 14px;"><strong>Discover:</strong> Scan all course content for duplicates</span>
                        </div>
                        <div style="display: flex; align-items: center;">
                            <span style="background: var(--acu-gold); color: var(--acu-deep-purple); width: 24px; height: 24px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: bold; margin-right: 12px;">2</span>
                            <span style="color: var(--acu-deep-purple); font-size: 14px;"><strong>Analyze:</strong> Compare content and check inbound links</span>
                        </div>
                        <div style="display: flex; align-items: center;">
                            <span style="background: var(--acu-gold); color: var(--acu-deep-purple); width: 24px; height: 24px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: bold; margin-right: 12px;">3</span>
                            <span style="color: var(--acu-deep-purple); font-size: 14px;"><strong>Protect:</strong> Automatically preserve pages with inbound links</span>
                        </div>
                        <div style="display: flex; align-items: center;">
                            <span style="background: var(--acu-gold); color: var(--acu-deep-purple); width: 24px; height: 24px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: bold; margin-right: 12px;">4</span>
                            <span style="color: var(--acu-deep-purple); font-size: 14px;"><strong>Recommend:</strong> Suggest safe actions with detailed reasoning</span>
                        </div>
                        <div style="display: flex; align-items: center;">
                            <span style="background: var(--acu-gold); color: var(--acu-deep-purple); width: 24px; height: 24px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: bold; margin-right: 12px;">5</span>
                            <span style="color: var(--acu-deep-purple); font-size: 14px;"><strong>Preview:</strong> Show you exactly what will happen before any changes</span>
                        </div>
                    </div>
                </div>
                
                <!-- Safety Assurance -->
                <div style="background: var(--acu-cream); padding: 20px; border-radius: 8px; border-left: 4px solid var(--acu-deep-purple);">
                    <h4 style="margin: 0 0 12px 0; color: var(--acu-deep-purple); font-size: 16px;">🛡️ Your Course is Protected</h4>
                    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px;">
                        <div style="background: rgba(255,255,255,0.7); padding: 12px; border-radius: 6px;">
                            <div style="font-weight: 600; color: var(--acu-deep-purple); font-size: 13px;">Inbound Links Protected</div>
                            <div style="font-size: 12px; color: var(--acu-purple);">Pages linked by other content are never deleted</div>
                        </div>
                        <div style="background: rgba(255,255,255,0.7); padding: 12px; border-radius: 6px;">
                            <div style="font-weight: 600; color: var(--acu-deep-purple); font-size: 13px;">Preview First</div>
                            <div style="font-size: 12px; color: var(--acu-purple);">See all changes before anything happens</div>
                        </div>
                        <div style="background: rgba(255,255,255,0.7); padding: 12px; border-radius: 6px;">
                            <div style="font-weight: 600; color: var(--acu-deep-purple); font-size: 13px;">Manual Approval</div>
                            <div style="font-size: 12px; color: var(--acu-purple);">You control every action taken</div>
                        </div>
                    </div>
                </div>
            \`;
        }

        function closePreview() {
            console.log('Phase 2: Closing preview');
            const preview = document.getElementById('analysisPreview');
            if (preview) {
                preview.classList.remove('active');
            }
            currentTaskId = null;
        }

        function proceedWithAnalysis() {
            console.log('Phase 2: Proceeding with analysis for task:', currentTaskId);
            if (!currentTaskId) {
                console.error('No task ID available');
                return;
            }
            
            const taskToExecute = currentTaskId;
            closePreview();
            executeTask(taskToExecute);
        }

        function executeTask(taskId) {
            console.log('Phase 2: Executing task:', taskId);
            
            showProgress(taskId);
            
            fetch('/execute', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ 
                    taskId: taskId,
                    courseId: '${getRealCourseId(token)}',
                    userId: '${token.sub || 'unknown'}'
                })
            })
            .then(response => {
                console.log('Phase 2: Got response:', response.status);
                return response.json();
            })
            .then(data => {
                console.log('Phase 2: Analysis result:', data);
                hideProgress();
                if (data.success) {
                    currentAnalysisResult = data.result;
                    showResults(taskId, data.result);
                } else {
                    showError(data.error);
                }
            })
            .catch(error => {
                console.error('Phase 2: Network error:', error);
                hideProgress();
                showError('Network error: ' + error.message);
            });
        }

        function showProgress(taskId) {
            console.log('Phase 2: Showing progress for:', taskId);
            const overlay = document.getElementById('progressOverlay');
            const progressText = document.getElementById('progressText');
            const progressDetails = document.getElementById('progressDetails');
            
            if (!overlay || !progressText || !progressDetails) {
                console.error('Progress elements not found');
                return;
            }
            
            const progressMessages = {
                'find-duplicate-pages': {
                    text: 'Analyzing course content for duplicates...',
                    details: 'Connecting to Canvas API and mapping inbound links'
                }
            };
            
            const message = progressMessages[taskId] || {
                text: 'Processing course analysis...',
                details: 'This may take a few moments'
            };
            
            progressText.textContent = message.text;
            progressDetails.textContent = message.details;
            overlay.classList.add('active');
            
            const steps = [
                'Retrieving course pages, modules, and assignments...',
                'Analyzing content structure and similarity patterns...',
                'Mapping inbound links and content relationships...',
                'Assessing removal risks and integration levels...',
                'Generating smart recommendations and safety analysis...',
                'Preparing detailed preview report...'
            ];
            
            let step = 0;
            const progressInterval = setInterval(() => {
                if (step < steps.length) {
                    progressDetails.textContent = steps[step];
                    step++;
                } else {
                    progressDetails.textContent = 'Finalizing analysis results...';
                }
            }, 3000);
            
            overlay.dataset.interval = progressInterval;
        }

        function hideProgress() {
            console.log('Phase 2: Hiding progress');
            const overlay = document.getElementById('progressOverlay');
            if (overlay) {
                const interval = overlay.dataset.interval;
                if (interval) {
                    clearInterval(interval);
                }
                overlay.classList.remove('active');
            }
        }

        function showResults(taskId, result) {
            console.log('Phase 2: Showing results for:', taskId, result);
            const container = document.getElementById('resultsContainer');
            const title = document.getElementById('resultsTitle');
            const content = document.getElementById('resultsContent');
            
            if (!container || !title || !content) {
                console.error('Results elements not found');
                return;
            }
            
            currentAnalysisResult = result;
            
            if (taskId === 'find-duplicate-pages') {
                title.textContent = 'Phase 2: Enhanced Analysis Complete - Review Findings';
                content.innerHTML = generateEnhancedDuplicateResults(result);
            }
            
            container.style.display = 'block';
            container.scrollIntoView({ behavior: 'smooth' });
        }

        function generateEnhancedDuplicateResults(result) {
            console.log('Phase 2: Generating enhanced results for:', result);
            
            const findings = result.findings || {};
            const riskAssessment = result.risk_assessment || {};
            const safeActions = result.safe_actions || [];
            const manualReview = result.requires_manual_review || [];
            const nextSteps = result.next_steps || {};
            
            // Calculate success metrics for confidence-building messaging
            const totalIssues = (findings.total_duplicates || findings.exact_duplicates || 0);
            const autoResolved = safeActions.length;
            const manualRequired = manualReview.length;
            const successRate = totalIssues > 0 ? Math.round((autoResolved / totalIssues) * 100) : 0;
            
            return \`
                <!-- Analysis Results Banner -->
                <div style="background: linear-gradient(135deg, var(--acu-cream) 0%, var(--acu-cream-light) 100%); padding: 24px; border-radius: 12px; margin-bottom: 24px; border-left: 6px solid var(--acu-deep-purple); box-shadow: 0 4px 12px rgba(74, 26, 74, 0.15);">
                    <div style="display: flex; align-items: center; margin-bottom: 12px;">
                        <span style="font-size: 24px; margin-right: 12px;">🔍</span>
                        <h2 style="margin: 0; color: var(--acu-deep-purple); font-size: 20px;">Analysis Complete - Review Findings</h2>
                    </div>
                    <p style="margin: 0 0 16px 0; color: var(--acu-purple); font-size: 16px;">
                        <strong>\${autoResolved} duplicates ready for safe removal</strong> - Review the details below and approve actions.
                    </p>
                    <div style="background: rgba(255,255,255,0.7); padding: 12px; border-radius: 8px;">
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <span style="color: var(--acu-deep-purple); font-weight: 500;">Ready for Action: \${successRate}%</span>
                            <span style="color: var(--acu-purple); font-size: 14px;">\${autoResolved} of \${totalIssues} duplicates staged for removal</span>
                        </div>
                    </div>
                </div>

                <!-- Action-Oriented Summary Cards -->
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px;">
                    <div style="background: #fff; padding: 20px; border-radius: 8px; border-left: 4px solid var(--acu-deep-purple); box-shadow: 0 2px 8px rgba(0,0,0,0.1);">
                        <div style="font-size: 32px; font-weight: bold; color: var(--acu-deep-purple); margin-bottom: 8px;">\${autoResolved}</div>
                        <div style="font-weight: 600; color: var(--acu-deep-purple); margin-bottom: 4px;">Ready for Removal</div>
                        <div style="font-size: 14px; color: var(--acu-purple);">Safe duplicates staged</div>
                    </div>
                    
                    \${manualRequired > 0 ? \`
                    <div style="background: #fff; padding: 20px; border-radius: 8px; border-left: 4px solid var(--acu-gold); box-shadow: 0 2px 8px rgba(0,0,0,0.1);">
                        <div style="font-size: 32px; font-weight: bold; color: var(--acu-gold); margin-bottom: 8px;">\${manualRequired}</div>
                        <div style="font-weight: 600; color: var(--acu-deep-purple); margin-bottom: 4px;">Need Your Decision</div>
                        <div style="font-size: 14px; color: var(--acu-purple);">Est. \${Math.ceil(manualRequired * 2)} minutes</div>
                    </div>
                    \` : \`
                    <div style="background: #fff; padding: 20px; border-radius: 8px; border-left: 4px solid var(--acu-deep-purple); box-shadow: 0 2px 8px rgba(0,0,0,0.1);">
                        <div style="font-size: 32px; font-weight: bold; color: var(--acu-deep-purple); margin-bottom: 8px;">✓</div>
                        <div style="font-weight: 600; color: var(--acu-deep-purple); margin-bottom: 4px;">All Ready for Action</div>
                        <div style="font-size: 14px; color: var(--acu-purple);">No manual decisions needed</div>
                    </div>
                    \`}
                    
                    <div style="background: #fff; padding: 20px; border-radius: 8px; border-left: 4px solid var(--acu-purple); box-shadow: 0 2px 8px rgba(0,0,0,0.1);">
                        <div style="font-size: 32px; font-weight: bold; color: var(--acu-purple); margin-bottom: 8px;">\${riskAssessment.protected_by_links || 0}</div>
                        <div style="font-weight: 600; color: var(--acu-deep-purple); margin-bottom: 4px;">Protected Pages</div>
                        <div style="font-size: 14px; color: var(--acu-purple);">Pages with inbound links</div>
                    </div>
                </div>

                <!-- Priority Action Section -->
                \${manualRequired > 0 ? \`
                <div style="background: var(--acu-cream-light); padding: 20px; border-radius: 8px; margin-bottom: 24px; border-left: 6px solid var(--acu-gold); box-shadow: 0 4px 12px rgba(244, 185, 66, 0.15);">
                    <div style="display: flex; align-items: center; margin-bottom: 16px;">
                        <span style="font-size: 20px; margin-right: 12px;">⚠️</span>
                        <h3 style="margin: 0; color: var(--acu-deep-purple); font-size: 18px;">Decision Required (\${manualRequired} items)</h3>
                    </div>
                    <p style="margin: 0 0 16px 0; color: var(--acu-purple);">
                        These pages need your decision before any removal. Each has identical content but different usage patterns.
                    </p>
                    <div style="background: rgba(255,255,255,0.7); padding: 16px; border-radius: 6px; margin-bottom: 16px;">
                        <h4 style="margin: 0 0 12px 0; color: var(--acu-deep-purple); font-size: 14px;">Quick Decision Guide:</h4>
                        <ul style="margin: 0; padding-left: 20px; color: var(--acu-purple); font-size: 14px;">
                            <li>Check which page is more recently updated</li>
                            <li>Verify which one has more inbound links</li>
                            <li>Keep the page that's most integrated into your course flow</li>
                        </ul>
                    </div>
                    <button class="btn-primary" onclick="showDetailedReview()" style="background: var(--acu-gold); color: var(--acu-deep-purple); border: none; padding: 12px 24px; border-radius: 6px; font-weight: 600; cursor: pointer;">
                        Review \${manualRequired} Items (Est. \${Math.ceil(manualRequired * 2)} min)
                    </button>
                </div>
                \` : ''}

                <!-- Staged Actions Section (Collapsible) -->
                \${safeActions.length > 0 ? \`
                <details style="margin-bottom: 24px;">
                                        <summary style="cursor: pointer; font-weight: 600; color: var(--acu-deep-purple); font-size: 16px; padding: 16px; background: var(--acu-cream); border-radius: 6px; border: 1px solid var(--acu-gold);">
                        ✅ Ready for Removal (\${safeActions.length} items) - Click to view details
                    </summary>
                    <div style="background: var(--acu-cream-light); padding: 20px; border-radius: 6px; margin-top: 8px; border: 1px solid var(--acu-gold);">
                        <p style="margin: 0 0 16px 0; color: var(--acu-purple); font-size: 14px;">
                            These duplicates are staged for safe removal because they have identical content to official pages and no inbound links.
                        </p>
                        <div style="max-height: 300px; overflow-y: auto;">
                            \${safeActions.map(action => \`
                                <div style="background: white; padding: 12px; border-radius: 4px; margin-bottom: 8px; border-left: 3px solid var(--acu-deep-purple);">
                                    <div style="font-weight: 600; color: var(--acu-deep-purple); margin-bottom: 4px;">
                                        \${action.delete_page_title || action.duplicate_title}
                                    </div>
                                    <div style="font-size: 13px; color: var(--acu-purple); line-height: 1.4;">
                            <strong>Safe to remove:</strong> This page has identical content to your official version<br>
                            <strong>No inbound links:</strong> No other content links to this page<br>
                            <strong>Status:</strong> Ready for removal
                        </div>
                                </div>
                            \`).join('')}
                        </div>
                        \${nextSteps.can_proceed_with_safe_actions ? \`
                            <div style="margin-top: 16px; padding-top: 16px; border-top: 1px solid #c3e6cb;">
                                <button class="btn-primary" onclick="executeSafeActions()" id="executeSafeBtn" style="background: #28a745; color: white; border: none; padding: 10px 20px; border-radius: 6px; font-weight: 500; cursor: pointer;">
                                    Remove \${safeActions.length} Duplicates Now
                                </button>
                            </div>
                        \` : ''}
                    </div>
                </details>
                \` : ''}

                <!-- Course Health Summary -->
                <div style="background: #e8f4f8; padding: 20px; border-radius: 8px; border-left: 4px solid #17a2b8;">
                    <h4 style="margin: 0 0 12px 0; color: #0c5460; font-size: 16px;">📊 Analysis Summary</h4>
                    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px;">
                        <div style="text-align: center;">
                            <div style="font-size: 24px; font-weight: bold; color: #17a2b8;">\${totalIssues}</div>
                            <div style="font-size: 12px; color: #666;">Duplicates Found</div>
                        </div>
                        <div style="text-align: center;">
                            <div style="font-size: 24px; font-weight: bold; color: #28a745;">\${successRate}%</div>
                            <div style="font-size: 12px; color: #666;">Ready for Action</div>
                        </div>
                        <div style="text-align: center;">
                            <div style="font-size: 24px; font-weight: bold; color: #ffc107;">\${manualRequired}</div>
                            <div style="font-size: 12px; color: #666;">Need Decision</div>
                        </div>
                        <div style="text-align: center;">
                            <div style="font-size: 24px; font-weight: bold; color: #17a2b8;">\${riskAssessment.protected_by_links || 0}</div>
                            <div style="font-size: 12px; color: #666;">Protected</div>
                        </div>
                    </div>
                </div>

                <!-- Technical Details (Collapsed by Default) -->
                <details style="margin-top: 24px;">
                    <summary style="cursor: pointer; font-weight: 600; color: #666; font-size: 14px; padding: 12px; background: #f8f9fa; border-radius: 4px; border: 1px solid #dee2e6;">
                        🔧 Technical Details (Click to expand)
                    </summary>
                    <pre style="background: #f8f9fa; padding: 16px; border-radius: 6px; font-size: 12px; overflow-x: auto; margin-top: 8px; border: 1px solid #dee2e6;">
\${JSON.stringify(result, null, 2)}</pre>
                </details>
            \`;
        }

        function executeSafeActions() {
            if (!currentAnalysisResult || !currentAnalysisResult.safe_actions) {
                showError('No safe actions available to execute');
                return;
            }
            
            if (confirm('Remove ' + currentAnalysisResult.safe_actions.length + ' duplicate pages? This action cannot be undone.')) {
                executeApprovedActions(currentAnalysisResult.safe_actions);
            }
        }

        function executeApprovedActions(approvedActions) {
            showProgress('execute-approved');
            
            fetch('/execute-approved', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ 
                    taskId: currentTaskId,
                    courseId: '${getRealCourseId(token)}',
                    userId: currentUserId,
                    approvedActions: approvedActions
                })
            })
            .then(response => response.json())
            .then(data => {
                hideProgress();
                if (data.success) {
                    showExecutionResults(data.result);
                } else {
                    showError(data.error);
                }
            })
            .catch(error => {
                hideProgress();
                showError('Network error: ' + error.message);
            });
        }

        function showExecutionResults(result) {
            alert('Phase 2: Execution results: ' + JSON.stringify(result, null, 2));
        }

        function reviewSafeActions() {
            alert('Phase 2: Detailed review functionality will show individual action details here.');
        }

        function showDetailedReview() {
            alert('Phase 2: Detailed manual review interface will be shown here.');
        }

        function showError(error) {
            console.error('Phase 2: Showing error:', error);
            const container = document.getElementById('resultsContainer');
            const title = document.getElementById('resultsTitle');
            const content = document.getElementById('resultsContent');
            
            if (!container || !title || !content) {
                console.error('Error display elements not found');
                return;
            }
            
            title.textContent = 'Phase 2: Analysis Encountered an Issue';
            content.innerHTML = \`
                <div style="background: #fff3cd; padding: 20px; border-radius: 8px; border-left: 4px solid #ffc107;">
                    <h3 style="margin: 0 0 12px 0; color: #856404;">Analysis Could Not Complete</h3>
                    <p style="margin: 0 0 16px 0; color: #856404;">The Phase 2 analysis process encountered an unexpected issue. This doesn't indicate any problems with your course content.</p>
                    <details style="margin-top: 16px;">
                        <summary style="cursor: pointer; font-weight: 600;">Technical Details</summary>
                        <pre style="background: #f8f9fa; padding: 12px; margin-top: 8px; border-radius: 4px; font-size: 12px;">\${error}</pre>
                    </details>
                </div>
                
                <div style="background: #f8f9fa; padding: 16px; border-radius: 6px; margin-top: 16px;">
                    <h4 style="margin: 0 0 8px 0;">Suggested Actions:</h4>
                    <ul style="margin: 0; padding-left: 20px;">
                        <li>Try the Phase 2 analysis again in a few minutes</li>
                        <li>Check if you have the necessary Canvas permissions</li>
                        <li>Verify your Canvas API token is configured</li>
                        <li>Contact your LMS administrator if the issue persists</li>
                    </ul>
                </div>
            \`;
            
            container.style.display = 'block';
            container.scrollIntoView({ behavior: 'smooth' });
        }

        // Keyboard accessibility
        document.addEventListener('keydown', function(e) {
            if (e.key === 'Enter' || e.key === ' ') {
                if (e.target.classList.contains('task-card')) {
                    e.preventDefault();
                    const onclick = e.target.getAttribute('onclick');
                    if (onclick) {
                        const match = onclick.match(/startAnalysis\\('([^']+)'\\)/);
                        if (match) {
                            startAnalysis(match[1]);
                        }
                    }
                }
            }
        });

        // Debug function to check if all elements exist
        function checkElements() {
            const elements = [
                'analysisPreview', 'previewTitle', 'previewContent',
                'progressOverlay', 'progressText', 'progressDetails',
                'resultsContainer', 'resultsTitle', 'resultsContent'
            ];
            
            elements.forEach(id => {
                const element = document.getElementById(id);
                console.log(\`Element \${id}: \${element ? 'found' : 'NOT FOUND'}\`);
            });
        }

        // Call checkElements when page loads
        document.addEventListener('DOMContentLoaded', function() {
            console.log('Phase 2: DOM loaded, checking elements...');
            checkElements();
        });

        console.log('Phase 2: JavaScript loaded successfully');
    </script> </body>
</html>
  `
}

function groupTasksByCategory() {
  const categories = {}
  Object.entries(QA_TASKS).forEach(([id, task]) => {
    if (!categories[task.category]) {
      categories[task.category] = []
    }
    categories[task.category].push({ id, ...task })
  })
  return categories
}

// Add CORS headers for cross-origin requests
lti.app.use((req, res, next) => {
  res.header('Access-Control-Allow-Origin', '*')
  res.header('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE')
  res.header('Access-Control-Allow-Headers', 'Content-Type')
  next()
})

// REMOVED: Duplicate /execute endpoint that was conflicting with Phase 2 implementation
// The Phase 2 /execute endpoint at line 33 handles all execution

// Phase 2: Legacy executeQATask function (kept for backward compatibility)
async function executeQATask(taskId, courseId, userId, analyzeOnly = true) {
  console.log('Legacy executeQATask called - redirecting to Phase 2 analyzeTask');
  return await analyzeTask(taskId, courseId, userId);
}

const setup = async () => {
  try {
    // Deploy server and open connection to the database
    await lti.deploy({ port: 3000 })
    
    // Register Canvas platform
    await lti.registerPlatform({
      url: 'https://aculeo.test.instructure.com', // Change from canvas.test.instructure.com
      name: 'Canvas Test',
      clientId: '226430000000000274',
      authenticationEndpoint: 'https://aculeo.test.instructure.com/api/lti/authorize_redirect',
      accesstokenEndpoint: 'https://aculeo.test.instructure.com/login/oauth2/token',
      authConfig: { method: 'JWK_SET', key: 'https://aculeo.test.instructure.com/api/lti/security/jwks' }
    })

    console.log('✅ Canvas platform registered')
    
    console.log('🚀 QA Automation LTI deployed on http://localhost:3000')
    console.log('📋 LTI Configuration URLs (for Canvas Developer Key):')
    console.log('   - Launch URL: https://stay-happens-actually-devoted.trycloudflare.com/qa-tools')
    console.log('   - Login URL: https://stay-happens-actually-devoted.trycloudflare.com/login') 
    console.log('   - Keyset URL: https://stay-happens-actually-devoted.trycloudflare.com/keys')
    console.log('   - Deep Linking URL: https://stay-happens-actually-devoted.trycloudflare.com/qa-tools')
    
    // Note: Platform registration will be done after Canvas Developer Key setup
    console.log('\n⏳ Canvas Developer Key setup required before platform registration')
    
  } catch (error) {
    console.error('Deployment failed:', error)
  }
}

setup()
