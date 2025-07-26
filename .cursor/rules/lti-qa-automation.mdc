---
alwaysApply: true
---
# Canvas LTI QA Automation Project Rules

## Project Context
Canvas LMS LTI 1.3 tool built with ltijs for QA automation tasks. Integrates Python scripts via Node.js.

## Architecture
- **Framework**: ltijs (LTI 1.3)
- **Database**: MongoDB
- **Scripts**: Python 3 automation
- **Tunnel**: Cloudflared (dev)

## Critical Configuration

### Canvas Platform Registration
```javascript
// ALWAYS use canvas.test.instructure.com for platform URL
await lti.registerPlatform({
  url: 'https://canvas.test.instructure.com', // Not subdomain!
  clientId: 'YOUR_CLIENT_ID',
  // ... other config
})
```

### Endpoint Whitelisting (REQUIRED)
```javascript
// MUST whitelist non-LTI endpoints
lti.whitelist('/execute')
lti.app.post('/execute', handler)
```

### Environment Variables
```
CANVAS_URL=aculeo.test.instructure.com
CANVAS_API_TOKEN=your_token
MONGODB_URL=mongodb://localhost:27017/qa-automation-lti
```

## Development Workflow
1. Start MongoDB: `brew services start mongodb-community`
2. Start tunnel: `cloudflared tunnel --url http://localhost:3000`
3. Update Canvas Developer Key with tunnel URL
4. Start LTI: `node qa-automation-lti.js`

## Adding New QA Scripts
- Place in `scripts/` folder
- Accept CLI args: `--canvas-url`, `--api-token`, `--course-id`
- Add to QA_TASKS object and executeQATask function
- Use `lti.whitelist()` for new endpoints