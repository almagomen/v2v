# Claude AI Workflow Guide

## Overview

This document explains how Claude manages the OpenReel project, reviews issues, implements fixes, and handles pull requests.

---

## 🚀 Current Setup (Phase 1 - Manual with Scripts)

### How It Works

1. **Issues are created** on GitHub by contributors
2. **GitHub Action labels them** with `needs-claude-review`
3. **Augustus runs a local script** that fetches labeled issues
4. **Claude reviews in CLI session**, generates fixes, creates PRs
5. **Augustus reviews Claude's work**, approves and merges
6. **Claude closes the issue** with resolution details

### Daily Workflow

```bash
# Morning: Check for new issues
pnpm claude:review-issues

# Claude will:
# - Fetch all issues labeled 'needs-claude-review'
# - Analyze each issue
# - Generate fixes or ask for clarification
# - Create PRs with fixes
# - Post updates to GitHub

# Afternoon: Check for PRs needing review
pnpm claude:review-prs

# Claude will:
# - Review all open PRs
# - Run tests and type checking
# - Provide detailed feedback
# - Approve or request changes
```

### Scripts Location

- `scripts/claude-issue-manager.ts` - Issue review and management
- `scripts/claude-pr-reviewer.ts` - PR review automation
- `.github/workflows/label-for-claude.yml` - Auto-labels new issues

---

## 🔧 Future Setup (Phase 2 - Automated)

### Architecture

```
GitHub Event → GitHub Webhook → Cloud Function → Claude API → GitHub Response
```

### Components

1. **GitHub App** - "Claude OpenReel Manager"
   - Permissions: Read/write issues, PRs, code, checks
   - Webhooks: issues, pull_request, issue_comment

2. **Cloud Function** (Vercel/Netlify/Railway)
   - Receives webhook events
   - Calls Claude API with context
   - Posts responses back to GitHub

3. **Claude API Integration**
   - Analyzes issues and generates fixes
   - Reviews PR code for quality
   - Runs tests and checks
   - Auto-merges when safe

### Safety Guardrails

- **Auto-merge only for**: Bug fixes, docs, tests, minor improvements
- **Human review required for**: New features, breaking changes, architecture changes
- **All PRs created by Claude** are labeled `ai-generated` for transparency
- **Test suite must pass** before any merge
- **Augustus has override** on all decisions

---

## 📋 Issue Workflow

### 1. New Issue Created

**Trigger:** User opens an issue

**Claude's Response:**
```markdown
Hi! I'm Claude, the AI assistant managing this project. I've reviewed your issue.

**Issue Type:** [Bug/Feature/Question]
**Priority:** [Critical/High/Medium/Low]
**Estimated Fix Time:** [Hours/Days]

**Analysis:**
[Claude's understanding of the issue]

**Proposed Solution:**
[How Claude plans to fix it]

I'm working on a fix now. I'll create a PR shortly.

---
*Note: This issue is being handled by Claude AI with human oversight from Augustus.*
```

### 2. Claude Investigates

```bash
# Claude runs automatically:
1. Read relevant code files
2. Search for similar issues
3. Check tests
4. Reproduce bug if possible
5. Identify root cause
```

### 3. Claude Creates Fix PR

```markdown
# PR Title: fix: [issue description] (#123)

## Summary
Fixes #123

## Root Cause
[Explanation of what was wrong]

## Solution
[What was changed and why]

## Testing
- [x] Existing tests pass
- [x] Added new test for regression
- [x] Manually tested in browser

## Files Changed
- `path/to/file.ts` - [description]

---
*This PR was created by Claude AI. Human review by Augustus pending.*
```

### 4. Augustus Reviews & Merges

```bash
# Augustus checks:
- Does the fix make sense?
- Are tests comprehensive?
- Any security concerns?
- Code quality acceptable?

# If approved:
gh pr merge 123 --squash

# Claude auto-closes issue with:
"Fixed in #123 and deployed to production. Thanks for reporting!"
```

---

## 🔍 PR Review Workflow

### External Contributor Opens PR

**Trigger:** New PR from community

**Claude's Auto-Review:**
```markdown
Thanks for the contribution! I've reviewed your PR.

## ✅ Automated Checks
- [x] TypeScript compiles
- [x] Tests pass (42/42)
- [x] Code follows style guide
- [x] No security vulnerabilities detected

## 📝 Code Review

### file.ts
**Line 45:** Consider using `useCallback` here to prevent unnecessary re-renders
**Line 67:** Great error handling!

### file2.ts
**Line 23:** This could be simplified to: `const result = data?.map(...) ?? []`

## 🎯 Overall Assessment
**Status:** Approved ✅
**Recommendation:** Merge after addressing minor suggestions above

Great work! This is a clean, well-tested contribution.

---
*Automated review by Claude AI. Final approval by Augustus required for merge.*
```

### Augustus Final Review

```bash
# Augustus checks:
- Claude's review is accurate
- No red flags missed
- Contributor followed up on feedback

# If all good:
gh pr merge 456 --squash

# Claude thanks contributor:
"Merged! Thanks for contributing to OpenReel 🎉"
```

---

## 🏷️ Label System

### Issue Labels (Auto-Applied)

- `needs-claude-review` - New issue, Claude hasn't reviewed yet
- `claude-reviewing` - Claude is actively working on it
- `claude-needs-info` - Claude needs more information from reporter
- `ready-for-fix` - Claude analyzed, ready to implement
- `ai-generated-pr` - PR created by Claude
- `human-review-required` - Needs Augustus to review

### Priority Labels

- `priority-critical` - Breaks core functionality
- `priority-high` - Important but not blocking
- `priority-medium` - Should fix soon
- `priority-low` - Nice to have

### Type Labels

- `type-bug` - Something isn't working
- `type-feature` - New functionality
- `type-docs` - Documentation improvements
- `type-performance` - Performance optimization
- `type-security` - Security issue

---

## 📊 Metrics & Reporting

### Weekly Summary (Auto-Generated)

Claude posts a weekly summary to Discussions:

```markdown
# OpenReel Weekly Summary - Jan 13-19, 2026

## 📈 Activity
- **Issues Reviewed:** 15
- **PRs Created:** 8
- **PRs Merged:** 12
- **Bugs Fixed:** 5
- **Features Shipped:** 2

## 🏆 Top Contributors
1. @contributor1 - 4 PRs
2. @contributor2 - 2 PRs

## 🐛 Bugs Fixed This Week
- #123 - Fix audio sync in variable speed
- #145 - Prevent memory leak in frame cache
- #167 - Fix undo/redo edge case

## ✨ New Features
- #134 - Add ripple editing
- #156 - Implement proxy workflow

## 📅 Next Week Focus
- Finish export system (Phase 2 milestone)
- Review community PRs
- Update documentation

---
*Generated by Claude AI*
```

---

## 🔐 Security & Safety

### What Claude CANNOT Do (Without Human Approval)

- ❌ Merge breaking changes
- ❌ Change security settings
- ❌ Modify GitHub Actions workflows
- ❌ Update dependencies (major versions)
- ❌ Delete branches or issues
- ❌ Change repository settings
- ❌ Grant access to collaborators

### What Claude CAN Do (Automatically)

- ✅ Review and label issues
- ✅ Create PRs for bug fixes
- ✅ Run tests and checks
- ✅ Comment on PRs with reviews
- ✅ Close resolved issues
- ✅ Update documentation
- ✅ Fix typos and formatting

### Safety Checks (Always Run)

```bash
# Before any code change:
1. pnpm typecheck     # TypeScript must pass
2. pnpm test          # All tests must pass
3. pnpm lint          # Code style must pass
4. Security scan      # No vulnerabilities

# If any fail: PR marked "needs-work", not merged
```

---

## 🛠️ Setup Instructions

### Phase 1: Manual Workflow (Current)

```bash
# 1. Set up GitHub CLI
gh auth login

# 2. Install dependencies
pnpm install

# 3. Add GitHub token to .env (for script access)
echo "GITHUB_TOKEN=your_token_here" >> .env.local

# 4. Run issue review
pnpm claude:review-issues

# 5. Run PR review
pnpm claude:review-prs
```

### Phase 2: Automated Workflow (Future)

**Requirements:**
- GitHub App created and installed
- Cloud function deployed (Vercel recommended)
- Anthropic API key in cloud function secrets
- Webhook configured

**Setup Steps:**
1. Create GitHub App with required permissions
2. Deploy cloud function (`/api/github-webhook`)
3. Configure webhook URL in GitHub App
4. Add secrets (ANTHROPIC_API_KEY, GITHUB_APP_KEY)
5. Test with a dummy issue
6. Monitor logs for first week
7. Gradually enable auto-merge

---

## 📝 Templates

### Issue Template (Auto-Posted by Claude)

```markdown
## Issue Analysis

**Status:** [Investigating/In Progress/Fixed]
**Priority:** [Critical/High/Medium/Low]
**Type:** [Bug/Feature/Question]

**Current Understanding:**
[What Claude understands the issue to be]

**Questions for Reporter:**
1. [Clarifying question 1]
2. [Clarifying question 2]

**Next Steps:**
- [ ] Reproduce issue locally
- [ ] Identify root cause
- [ ] Create fix PR
- [ ] Add regression test

I'll update this issue as I make progress.
```

### PR Template (Auto-Generated by Claude)

```markdown
## Description
[What this PR does]

## Related Issue
Fixes #[issue number]

## Changes Made
- [Change 1]
- [Change 2]

## Testing
- [x] All existing tests pass
- [x] Added tests for new functionality
- [x] Manually tested in browser

## Screenshots (if UI changes)
[Before/After screenshots]

## Checklist
- [x] TypeScript compiles
- [x] Code follows style guide
- [x] Documentation updated
- [x] No console.logs or debug code

---
*This PR was created by Claude AI*
```

---

## 💡 Best Practices

### For Contributors

1. **Be specific in issues** - The more details you provide, the better Claude can help
2. **Include reproduction steps** - For bugs, include exact steps to reproduce
3. **Add screenshots/videos** - Visual aids help Claude understand UI issues
4. **Respond to Claude's questions** - Claude may need clarification
5. **Be patient** - Claude typically responds within 24 hours

### For Augustus (Human Oversight)

1. **Daily check-in** - Review Claude's PRs and issue responses
2. **Override when needed** - If Claude misunderstands, correct it
3. **Monitor metrics** - Check weekly summaries for anomalies
4. **Approve major changes** - New features need human approval
5. **Engage community** - Thank contributors, provide direction

---

## 🔄 Continuous Improvement

### Feedback Loop

1. **Track Claude's accuracy** - How many PRs needed revision?
2. **User satisfaction** - Are issue reporters happy with responses?
3. **Response time** - Average time from issue to fix
4. **Code quality** - Are Claude's fixes creating new bugs?

### Monthly Review

Augustus reviews:
- Claude's performance metrics
- Community feedback
- Areas for improvement
- Adjust prompts/workflows as needed

---

## 📞 Escalation

### When Claude Needs Help

If Claude encounters:
- **Ambiguous requirements** → Labels `claude-needs-info`, asks questions
- **Complex architecture decision** → Labels `human-review-required`, tags Augustus
- **Controversial change** → Creates RFC in Discussions, waits for community input
- **Security concern** → Immediately tags Augustus, doesn't auto-merge

### Contact

- **GitHub Discussions** - General questions about Claude's role
- **GitHub Issues** - Report issues with Claude's responses
- **Email Augustus** - For urgent concerns

---

**This is a living document.** As we learn and improve the workflow, this guide will be updated.
