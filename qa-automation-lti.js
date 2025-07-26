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

// Whitelist the execute endpoint
lti.whitelist('/execute')

// Add the endpoint
lti.app.post('/execute', async (req, res) => {
  const { taskId, courseId, userId } = req.body
  console.log(`Executing QA task: ${taskId} for course: ${courseId}`)
  
  try {
    const result = await executeQATask(taskId, courseId, userId)
    res.json({ success: true, taskId, result })
  } catch (error) {
    console.error('QA Task execution error:', error)
    res.json({ success: false, error: error.message })
  }
})

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
lti.onConnect((token, req, res) => {
  console.log('LTI Launch Token:', {
    iss: token.iss,
    aud: token.aud,
    sub: token.sub,
    context: token.platformContext
  })

  // Render QA Tools Dashboard
  const html = generateQADashboard(token)
  return res.send(html)
})

// Generate the QA Tools Dashboard HTML
function generateQADashboard(token) {
  const taskCategories = groupTasksByCategory()
  
  return `
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Canvas QA Automation Suite</title>
    <style>
        body { 
            font-family: 'Segoe UI', system-ui, sans-serif; 
            margin: 0; 
            padding: 20px; 
            background: #f5f5f5; 
        }
        .header {
            background: white;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .task-category {
            background: white;
            margin-bottom: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .category-header {
            background: #0374b5;
            color: white;
            padding: 15px 20px;
            border-radius: 8px 8px 0 0;
            font-weight: 600;
        }
        .task-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 15px;
            padding: 20px;
        }
        .task-card {
            border: 1px solid #e1e1e1;
            border-radius: 6px;
            padding: 15px;
            cursor: pointer;
            transition: all 0.2s;
            background: #fafafa;
        }
        .task-card:hover {
            border-color: #0374b5;
            background: white;
            transform: translateY(-2px);
            box-shadow: 0 4px 8px rgba(0,0,0,0.1);
        }
        .task-name { 
            font-weight: 600; 
            color: #333; 
            margin-bottom: 8px;
        }
        .task-description { 
            color: #666; 
            font-size: 14px; 
        }
        .user-info {
            background: #e8f4f8;
            padding: 10px;
            border-radius: 4px;
            font-size: 13px;
            color: #0374b5;
        }
        .btn {
            background: #0374b5;
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 4px;
            cursor: pointer;
            font-weight: 500;
        }
        .btn:hover { background: #025a87; }
    </style>
</head>
<body>
    <div class="header">
        <h1>🔧 Canvas QA Automation Suite</h1>
        <p>Select a QA automation task to streamline your Canvas course management workflow.</p>
        <div class="user-info">
            User: ${token.given_name || 'Unknown'} ${token.family_name || ''} | 
            Course: ${token.platformContext?.title || 'Unknown Course'}
        </div>
    </div>

    ${Object.entries(taskCategories).map(([category, tasks]) => `
        <div class="task-category">
            <div class="category-header">${category}</div>
            <div class="task-grid">
                ${tasks.map(task => `
                    <div class="task-card" onclick="executeTask('${task.id}')">
                        <div class="task-name">${task.name}</div>
                        <div class="task-description">${task.description}</div>
                    </div>
                `).join('')}
            </div>
        </div>
    `).join('')}

    <script>
        function executeTask(taskId) {
            console.log('Executing task:', taskId);
            fetch('/execute', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ 
                    taskId: taskId,
                    courseId: '280', // Extract from context.context.id or use hardcoded
                    userId: 'ea944eb8-3efb-4d76-8e79-deb888e4fc21'
                })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    alert('Task completed successfully: ' + JSON.stringify(data.result));
                } else {
                    alert('Task failed: ' + data.error);
                }
            });
        }
    </script>
</body>
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

// API endpoint to execute QA tasks - on main app route
lti.app.post('/execute', async (req, res) => {
  const { taskId, courseId, userId } = req.body
  
  try {
    console.log(`Executing QA task: ${taskId} for course: ${courseId}`)
    
    // Here you'll integrate with your Python automation scripts
    // For now, we'll simulate the execution
    const result = await executeQATask(taskId, courseId, userId)
    
    res.json({ 
      success: true, 
      taskId,
      result: result 
    })
  } catch (error) {
    console.error('QA Task execution error:', error)
    res.json({ 
      success: false, 
      error: error.message 
    })
  }
})

// Placeholder for Python script integration
async function executeQATask(taskId, courseId, userId) {
  const { spawn } = require('child_process');
  const path = require('path');
  
  switch (taskId) {
    case 'find-duplicate-pages':
      return new Promise((resolve, reject) => {
        // Path to your Python script
        const scriptPath = path.join(__dirname, 'scripts', 'duplicate_page_cleaner.py');
        
        // Get Canvas credentials from environment or config
        const canvasUrl = process.env.CANVAS_URL || 'aculeo.test.instructure.com';
        const apiToken = process.env.CANVAS_API_TOKEN || '';
        
        if (!apiToken) {
          reject(new Error('Canvas API token not configured'));
          return;
        }
        
        // Execute Python script
        const python = spawn('python3', [
          scriptPath,
          '--canvas-url', canvasUrl,
          '--api-token', apiToken,
          '--course-id', courseId,
          '--similarity-threshold', '0.7',
          '--auto-delete', 'true'
        ]);
        
        let output = '';
        let error = '';
        
        python.stdout.on('data', (data) => {
          output += data.toString();
        });
        
        python.stderr.on('data', (data) => {
          error += data.toString();
        });
        
        python.on('close', (code) => {
          if (code === 0) {
            // Parse output for results
            const lines = output.split('\n');
            const results = {
              message: 'Duplicate page analysis completed',
              output: output,
              report_generated: lines.some(line => line.includes('Consolidated report generated')),
              deleted_count: (output.match(/Deleted: (\d+) exact duplicates/) || [,0])[1]
            };
            resolve(results);
          } else {
            reject(new Error(`Python script failed: ${error}`));
          }
        });
      });
    
    default:
      throw new Error(`Unknown task: ${taskId}`)
  }
}

const setup = async () => {
  try {
    // Deploy server and open connection to the database
    await lti.deploy({ port: 3000 })
    
    // Register Canvas platform
    await lti.registerPlatform({
      url: 'https://canvas.test.instructure.com',
      name: 'Canvas Test',
      clientId: '226430000000000274',
      authenticationEndpoint: 'https://canvas.test.instructure.com/api/lti/authorize_redirect',
      accesstokenEndpoint: 'https://canvas.test.instructure.com/login/oauth2/token',
      authConfig: { method: 'JWK_SET', key: 'https://canvas.test.instructure.com/api/lti/security/jwks' }
    })

    console.log('✅ Canvas platform registered')
    
    console.log('🚀 QA Automation LTI deployed on http://localhost:3000')
    console.log('📋 LTI Configuration URLs:')
    console.log('   - Launch URL: http://localhost:3000/qa-tools')
    console.log('   - Login URL: http://localhost:3000/login') 
    console.log('   - Keyset URL: http://localhost:3000/keys')
    console.log('   - Deep Linking URL: http://localhost:3000/qa-tools')
    
    // Note: Platform registration will be done after Canvas Developer Key setup
    console.log('\n⏳ Canvas Developer Key setup required before platform registration')
    
  } catch (error) {
    console.error('Deployment failed:', error)
  }
}

setup()