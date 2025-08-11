# QA Automation LTI Troubleshooting Guide

## 🚨 **Critical Issue: Node.js Server Won't Start After Computer Restart**

### **Problem Summary**
After computer restart, the LTI server would start but not bind to port 3000, causing "connection refused" errors.

### **Root Cause**
Corrupted npm packages after system restart. Node.js processes would start but fail to bind to network ports.

### **Solution Steps**
1. **Kill all processes:**
   ```bash
   pkill -f "node qa-automation-lti.js"
   pkill -f cloudflared
   ```

2. **Remove corrupted packages:**
   ```bash
   rm -rf node_modules package-lock.json
   ```

3. **Fresh npm install:**
   ```bash
   npm install
   ```

4. **Test with simple server:**
   ```bash
   # Create test-server.js with basic Express server
   node test-server.js
   curl http://localhost:3000/test
   ```

5. **Start LTI server:**
   ```bash
   node qa-automation-lti.js
   ```

### **Verification**
- ✅ Simple Express server works on port 3000
- ✅ LTI server responds with 401 (expected for unauthenticated access)
- ✅ Tunnel works: `curl https://[tunnel-url]/qa-tools`

## 🔄 **Tunnel URL Management**

### **Issue**
Cloudflared generates new random URLs on each restart.

### **Solution**
1. Start fresh tunnel: `cloudflared tunnel --url http://localhost:3000`
2. Extract new URL from logs
3. Update LTI config with new URL
4. Update Canvas Developer Key

### **Current Working URLs (2025-08-07)**
- **Tunnel URL:** `https://trim-cartoons-describing-faster.trycloudflare.com`
- **Target Link URI:** `https://trim-cartoons-describing-faster.trycloudflare.com/qa-tools`
- **Redirect URIs:** `https://trim-cartoons-describing-faster.trycloudflare.com`
- **Public JWK URL:** `https://trim-cartoons-describing-faster.trycloudflare.com/keys`

## 📋 **Restore Point Analysis**

**Question:** Did we need to revert to restore points?

**Answer:** **NO** - The issue was environmental (npm packages), not code-related. We used the current working version and just updated the tunnel URL.

**Key Lesson:** Always try environmental fixes (npm reinstall, restart services) before reverting code changes.

## 🛠️ **Prevention Checklist**

After any computer restart:
1. ✅ Restart MongoDB: `brew services restart mongodb-community@6.0`
2. ✅ Fresh npm install: `rm -rf node_modules package-lock.json && npm install`
3. ✅ Start fresh tunnel and get new URL
4. ✅ Update Canvas Developer Key with new tunnel URL
5. ✅ Test LTI server startup

## 📞 **Quick Diagnostic Commands**

```bash
# Check if MongoDB is running
brew services list | grep mongodb

# Test MongoDB connection
mongosh --eval "db.adminCommand('ping')" --quiet

# Check if port 3000 is available
lsof -i :3000

# Test basic Node.js functionality
node -e "console.log('Node.js works'); process.exit(0);"

# Test simple Express server
node test-server.js
curl http://localhost:3000/test
```
