# LTI Design Principles
**Version:** 1.0 (Canvas API Validated)  
**Purpose:** Human-centered design within Canvas API and LTI technical constraints  
**Status:** **Primary Design Document** - Use this for all development decisions

---

## 🎯 **Philosophy: Human-Centered Within Technical Reality**

LTI exists to **reduce the emotional and cognitive burden** of Canvas course quality assurance while working within Canvas API and LTI limitations. Every design decision should prioritize:

1. **Learning Technologist confidence** in course quality
2. **Reduced anxiety** about manual QA processes  
3. **Preserved agency** and control over automation
4. **Realistic workflow integration** given Canvas constraints

---

## ✅ **What We CAN Actually Implement**

### **1. Rich Transparency & Explainability** ✅ **FULLY ACHIEVABLE**

**Canvas API Support:**
- ✅ Access to all content metadata (course, page, assignment details)
- ✅ Full content text for analysis
- ✅ User permissions and roles
- ✅ Course structure and navigation

**Implementation:**
```python
def provide_rich_context(scan_results):
    return {
        "what_scanned": f"47 links across {len(pages)} pages in {course.name}",
        "scan_method": "HTTP HEAD requests with 30-second timeout",
        "confidence_explained": {
            "high": "Server returned definitive 404/500 error",
            "medium": "Timeout or redirect detected",
            "low": "Unusual response pattern"
        },
        "impact_explanation": {
            "critical": "Students cannot access required content",
            "important": "May frustrate or confuse students",
            "minor": "Cosmetic or optimization opportunity"
        }
    }
```

### **2. Sophisticated Cognitive Load Reduction** ✅ **FULLY ACHIEVABLE**

**Our Interface Can:**
- ✅ Group findings by urgency, impact, and effort to fix
- ✅ Show clear progress through complex tasks
- ✅ Provide step-by-step guidance
- ✅ Prioritize actions by student impact

**Implementation:**
```html
<!-- Rich, organized interface within our LTI tool -->
<div class="qa-results">
  <div class="priority-critical">
    <h3>🚨 Critical - Fix Before Students Arrive</h3>
    <div class="issue-card">
      <h4>Assignment 2: Video Link Broken</h4>
      <p><strong>Impact:</strong> 150 students cannot watch required lecture</p>
      <p><strong>Location:</strong> Week 3 > Assignment Instructions</p>
      <p><strong>Fix:</strong> Replace with working backup link</p>
      <button>Auto-fix with backup</button>
      <button>Manual review</button>
    </div>
  </div>
  
  <div class="priority-important">
    <h3>⚠️ Important - Fix This Week</h3>
    <!-- More organized, contextual information -->
  </div>
</div>
```

### **3. Trust Through Preview & Confirmation** ⚠️ **PARTIALLY ACHIEVABLE**

**What We CAN Do:**
- ✅ Show exact preview of all changes before applying
- ✅ Require explicit user confirmation for each category
- ✅ Provide detailed change logs
- ✅ Create content backups before modifications

**What We CAN'T Do:**
- ❌ True one-click undo (Canvas API limitation)
- ❌ Atomic transactions across multiple Canvas API calls
- ❌ Version control integration

**Realistic Implementation:**
```python
class TrustBuiltModifications:
    def preview_changes(self, proposed_changes):
        return {
            "total_changes": len(proposed_changes),
            "by_risk_level": {
                "safe_auto_fix": auto_fixable_changes,
                "needs_review": manual_review_changes,
                "high_risk": destructive_changes
            },
            "backup_strategy": "Content exported to backup file",
            "undo_process": "Manual restore from backup if needed"
        }
    
    def require_explicit_consent(self):
        return {
            "safe_changes": "User can approve batch",
            "risky_changes": "Requires individual approval",
            "destructive": "Requires manual execution"
        }
```

### **4. Workflow Integration (Within LTI Constraints)** ✅ **ACHIEVABLE**

**Canvas Integration Points:**
- ✅ LTI 1.3 single sign-on with Canvas roles
- ✅ Course-specific tool launches
- ✅ Deep linking to specific Canvas content
- ✅ Grade passback for audit trails (optional)

**Workflow Support:**
```python
class WorkflowIntegration:
    def pre_semester_qa(self):
        # Comprehensive scan before course opens
        return {
            "scope": "All course content",
            "urgency": "Fix critical issues",
            "output": "Readiness checklist for LT review"
        }
    
    def emergency_fix_mode(self):
        # Student reported an issue
        return {
            "scope": "Specific content area",
            "urgency": "Immediate fix needed", 
            "output": "Direct link to fix location in Canvas"
        }
```

### **5. Emotional Experience Design** ✅ **FULLY ACHIEVABLE**

**Interface Design for Confidence:**
- ✅ Clear progress indicators
- ✅ Reassuring language and tone
- ✅ Celebration of successful completion
- ✅ Gentle handling of errors and issues

**Implementation:**
```html
<!-- Emotionally supportive interface -->
<div class="scan-complete">
  <h2>🎉 Great News! Your course is 94% student-ready</h2>
  <p>You've maintained excellent course quality. Just 3 minor items need attention.</p>
  
  <div class="confidence-builder">
    <p>✅ All critical learning materials are accessible</p>
    <p>✅ Assignment links are working perfectly</p>
    <p>✅ Due dates align with your term calendar</p>
  </div>
  
  <div class="next-steps">
    <h3>Optional Improvements (5 minutes to complete):</h3>
    <!-- Gentle, non-stressful presentation -->
  </div>
</div>
```

---

## ❌ **What We Must Abandon or Redesign**

### **1. In-Context Fixing**
**Original Vision:** Fix broken links directly in Canvas page editor  
**Canvas Reality:** Cannot modify Canvas interface  
**Realistic Alternative:** 
- Provide direct links to Canvas edit pages
- Show exact location instructions
- Copy-paste ready replacement text

```python
# Instead of inline fixes, provide precise guidance
def generate_fix_instructions(broken_link):
    return {
        "canvas_edit_url": f"{canvas_url}/courses/{course_id}/pages/{page_id}/edit",
        "location_instructions": "Find line 15, paragraph 3",
        "current_text": "https://broken-site.com/resource",
        "replacement_text": "https://working-site.com/resource",
        "copy_paste_ready": True
    }
```

### **2. Real-Time Integration**  
**Original Vision:** Validate links as LT types in Canvas editor  
**Canvas Reality:** Cannot hook into Canvas editing events  
**Realistic Alternative:** Scheduled scans with email notifications

### **3. Seamless Undo**
**Original Vision:** One-click undo for all changes  
**Canvas Reality:** Canvas API doesn't support transactions  
**Realistic Alternative:** 
- Comprehensive backups before changes
- Detailed change logs for manual restoration
- Conservative defaults requiring explicit approval

---

## ✅ **Revised Implementation Priorities**

### **High Impact, Technically Feasible:**

1. **Rich Information Architecture** within our LTI interface
2. **Intelligent Prioritization** of issues by student impact
3. **Comprehensive Preview** systems before making changes
4. **Clear Progress Communication** throughout processes
5. **Emotional Support** through interface design and language

### **Medium Impact, Requires Workarounds:**

1. **Guided Manual Fixes** (cannot be fully automated)
2. **Backup and Restore** workflows (manual process)
3. **Cross-Tool Integration** (limited by Canvas API)

### **Low Priority, High Technical Difficulty:**

1. **Real-time validation** (not possible with current Canvas architecture)
2. **In-context editing** (blocked by Canvas security model)
3. **Atomic operations** (Canvas API limitation)

---

## 🎯 **Realistic Success Metrics**

### **What We Can Measure:**
- ✅ Time reduction in QA processes
- ✅ Error detection accuracy
- ✅ User confidence scores (surveys)
- ✅ Tool adoption and usage patterns

### **What We Cannot Measure:**
- ❌ Real-time user behavior in Canvas
- ❌ Seamless workflow integration metrics
- ❌ In-context interaction success

---

## 📋 **Implementation Guidelines**

### **For Each Feature, Ask:**

1. **Can Canvas API provide the data needed?** ✅/❌
2. **Can we present this clearly in our LTI interface?** ✅/❌
3. **Do we need to modify Canvas itself?** (If yes, probably not feasible)
4. **Can we provide value even with workarounds?** ✅/❌

### **Decision Framework:**
- **Green Light:** Uses Canvas API data, works within LTI constraints
- **Yellow Light:** Requires workarounds but still valuable
- **Red Light:** Requires Canvas modification or unavailable API

---

*This revised framework ensures we design for human needs within Canvas technical constraints.*