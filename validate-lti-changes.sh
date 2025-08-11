#!/bin/bash
# LTI QA Guard Rail Validation Script
# Run this before committing any changes to ensure nothing is broken
# Usage: ./validate-lti-changes.sh

set -e  # Exit on any error

echo "🛡️  LTI Guard Rail Validation Starting..."
echo "======================================"

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Track validation results
VALIDATION_PASSED=true

# Function to print status
print_status() {
    if [ "$2" = "PASS" ]; then
        echo -e "${GREEN}✅ $1${NC}"
    elif [ "$2" = "FAIL" ]; then
        echo -e "${RED}❌ $1${NC}"
        VALIDATION_PASSED=false
    else
        echo -e "${YELLOW}⚠️  $1${NC}"
    fi
}

# Function to check if file was modified
check_protected_file() {
    local file=$1
    if git diff --name-only HEAD~1 HEAD 2>/dev/null | grep -q "^$file$"; then
        print_status "CRITICAL: Protected file $file was modified!" "FAIL"
        echo "   🚨 This file should NEVER be modified for new features"
        return 1
    else
        print_status "Protected file $file unchanged" "PASS"
        return 0
    fi
}

echo "🔍 Phase 1: Protected File Validation"
echo "------------------------------------"

# Check critical protected files
check_protected_file "scripts/duplicate_page_cleaner.py"

# Check if qa-automation-lti.js was modified (allow additions only)
if git diff --name-only HEAD~1 HEAD 2>/dev/null | grep -q "qa-automation-lti.js"; then
    # Check if only additions were made (no deletions of existing code)
    DELETIONS=$(git diff HEAD~1 HEAD qa-automation-lti.js | grep -c "^-" | grep -v "^---" || echo "0")
    if [ "$DELETIONS" -gt 0 ]; then
        print_status "qa-automation-lti.js has deletions - possible breaking change!" "FAIL"
    else
        print_status "qa-automation-lti.js - additions only detected" "PASS"
    fi
fi

echo ""
echo "🧪 Phase 2: Code Pattern Validation"
echo "-----------------------------------"

# Check for new Python scripts and validate their structure
NEW_SCRIPTS=$(find scripts/ -name "*.py" -newer scripts/duplicate_page_cleaner.py 2>/dev/null || echo "")

if [ -n "$NEW_SCRIPTS" ]; then
    for script in $NEW_SCRIPTS; do
        echo "Validating new script: $script"
        
        # Check for required argument parsing
        if grep -q "analyze-only" "$script" && (grep -q "execute-approved" "$script" || grep -q "execute-from-json" "$script"); then
            print_status "$script has required argument parsing" "PASS"
        else
            print_status "$script missing required arguments (--analyze-only, --execute-approved/--execute-from-json)" "FAIL"
        fi
        
        # Check for Phase 2 JSON output format
        if grep -q "preview_first" "$script" && grep -q "safe_actions" "$script"; then
            print_status "$script follows Phase 2 JSON format" "PASS"
        else
            print_status "$script missing Phase 2 JSON output format" "FAIL"
        fi
    done
else
    print_status "No new Python scripts detected" "PASS"
fi

echo ""
echo "🚀 Phase 3: Runtime Validation"
echo "------------------------------"

# Check if Node.js dependencies are intact
if npm list --depth=0 >/dev/null 2>&1; then
    print_status "NPM dependencies intact" "PASS"
else
    print_status "NPM dependency issues detected" "FAIL"
fi

# Validate LTI can start without errors
echo "Testing LTI startup..."
timeout 10s node -c qa-automation-lti.js 2>/dev/null
if [ $? -eq 0 ]; then
    print_status "LTI syntax validation passed" "PASS"
else
    print_status "LTI syntax errors detected" "FAIL"
fi

echo ""
echo "🎯 Phase 4: Task Integrity Check"
echo "--------------------------------"

# Validate QA_TASKS structure in qa-automation-lti.js
if [ -f "qa-automation-lti.js" ]; then
    # Check if duplicate-pages task still exists
    if grep -q "find-duplicate-pages" qa-automation-lti.js; then
        print_status "Core duplicate-pages task preserved" "PASS"
    else
        print_status "Core duplicate-pages task missing!" "FAIL"
    fi
    
    # Count number of tasks (should only increase, never decrease)
    TASK_COUNT=$(grep -c "name:" qa-automation-lti.js || echo "0")
    echo "   📊 Total QA tasks detected: $TASK_COUNT"
fi

echo ""
echo "🔐 Phase 5: Security & Best Practices"
echo "------------------------------------"

# Check for potential security issues in new code
if git diff HEAD~1 HEAD | grep -i "eval\|exec\|system" >/dev/null 2>&1; then
    print_status "Potential security risk: eval/exec/system usage detected" "FAIL"
else
    print_status "No obvious security risks in changes" "PASS"
fi

# Check for console.log statements (should use proper logging)
if git diff HEAD~1 HEAD | grep "console\.log" >/dev/null 2>&1; then
    print_status "Warning: console.log statements found - consider proper logging" "WARN"
fi

echo ""
echo "📋 Validation Summary"
echo "===================="

if [ "$VALIDATION_PASSED" = true ]; then
    echo -e "${GREEN}🎉 ALL VALIDATIONS PASSED${NC}"
    echo "✅ Safe to proceed with deployment"
    echo ""
    echo "Next steps:"
    echo "1. Manual test existing duplicate page cleaner task"
    echo "2. Test new functionality end-to-end"
    echo "3. Verify Canvas API integration"
    exit 0
else
    echo -e "${RED}❌ VALIDATION FAILED${NC}"
    echo "🚨 Do NOT deploy these changes"
    echo ""
    echo "Required actions:"
    echo "1. Fix all FAIL items above"
    echo "2. Re-run this validation script"
    echo "3. Manual testing of existing functionality"
    exit 1
fi