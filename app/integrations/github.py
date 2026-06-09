"""
KazmaAI GitHub Integration Module

Provides:
- Repository management (clone, create, fork)
- Pull request operations (create, review, merge)
- Issue tracking (create, triage, label)
- Code review automation
- Activity monitoring
"""

import asyncio
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from github import Github, Auth
    from github.Repository import Repository
    from github.PullRequest import PullRequest
    from github.Issue import Issue
    PYGITHUB_AVAILABLE = True
except ImportError:
    PYGITHUB_AVAILABLE = False
    Github = None


@dataclass
class GitHubConfig:
    """GitHub configuration."""
    token: str
    username: Optional[str] = None
    base_url: Optional[str] = None  # For GitHub Enterprise
    default_repo: Optional[str] = None


@dataclass
class PRReview:
    """Pull request review result."""
    pr_number: int
    repo: str
    summary: str
    issues: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    security_findings: List[str] = field(default_factory=list)
    quality_score: float = 0.0
    ready_to_merge: bool = False


class GitHubClient:
    """
    GitHub API client for KazmaAI.
    
    Features:
    - Repository management
    - PR creation and review
    - Issue tracking
    - Code review automation
    """
    
    def __init__(self, config: GitHubConfig):
        """
        Initialize GitHub client.
        
        Args:
            config: GitHub configuration
        """
        self.config = config
        
        if not PYGITHUB_AVAILABLE:
            raise ImportError("PyGithub not installed. Run: pip install PyGithub")
        
        # Initialize GitHub client
        if config.base_url:
            # Enterprise
            auth = Auth.Token(config.token)
            self.gh = Github(auth=auth, base_url=config.base_url)
        else:
            # GitHub.com
            auth = Auth.Token(config.token)
            self.gh = Github(auth=auth)
        
        # Current user
        self.user = self.gh.get_user()
        
        # Cache for repos
        self._repo_cache: Dict[str, Repository] = {}
    
    def get_repo(self, repo_name: Optional[str] = None) -> Repository:
        """
        Get repository by name.
        
        Args:
            repo_name: Full name (user/repo) or None for default
            
        Returns:
            Repository object
        """
        name = repo_name or self.config.default_repo
        
        if not name:
            raise ValueError("No repository specified and no default configured")
        
        # Check cache
        if name in self._repo_cache:
            return self._repo_cache[name]
        
        # Get from GitHub
        try:
            repo = self.gh.get_repo(name)
            self._repo_cache[name] = repo
            return repo
        except Exception as e:
            raise RuntimeError(f"Failed to get repo '{name}': {e}")
    
    def list_repos(self, limit: int = 20) -> List[Dict[str, Any]]:
        """
        List user's repositories.
        
        Args:
            limit: Max number of repos
            
        Returns:
            List of repo info dicts
        """
        repos = []
        
        for repo in self.user.get_repos()[:limit]:
            repos.append({
                "name": repo.name,
                "full_name": repo.full_name,
                "description": repo.description,
                "private": repo.private,
                "stars": repo.stargazers_count,
                "forks": repo.forks_count,
                "updated_at": repo.updated_at.isoformat(),
                "url": repo.html_url,
            })
        
        return repos
    
    def create_repo(
        self,
        name: str,
        description: str = "",
        private: bool = False,
        auto_init: bool = True,
    ) -> Dict[str, Any]:
        """
        Create a new repository.
        
        Args:
            name: Repository name
            description: Description
            private: Whether private
            auto_init: Initialize with README
            
        Returns:
            Repo info dict
        """
        repo = self.user.create_repo(
            name=name,
            description=description,
            private=private,
            auto_init=auto_init,
        )
        
        self._repo_cache[repo.full_name] = repo
        
        return {
            "name": repo.name,
            "full_name": repo.full_name,
            "url": repo.html_url,
            "clone_url": repo.clone_url,
            "ssh_url": repo.ssh_url,
        }
    
    # =========================================================================
    # PULL REQUESTS
    # =========================================================================
    
    def create_pr(
        self,
        title: str,
        body: str,
        head: str,
        base: str = "main",
        repo_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a pull request.
        
        Args:
            title: PR title
            body: PR description
            head: Source branch
            base: Target branch
            repo_name: Repository name
            
        Returns:
            PR info dict
        """
        repo = self.get_repo(repo_name)
        
        pr = repo.create_pull(
            title=title,
            body=body,
            head=head,
            base=base,
        )
        
        return {
            "number": pr.number,
            "title": pr.title,
            "url": pr.html_url,
            "state": pr.state,
            "created_at": pr.created_at.isoformat(),
        }
    
    def get_pr(self, pr_number: int, repo_name: Optional[str] = None) -> PullRequest:
        """Get pull request by number."""
        repo = self.get_repo(repo_name)
        return repo.get_pull(pr_number)
    
    def list_prs(
        self,
        state: str = "open",
        repo_name: Optional[str] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        List pull requests.
        
        Args:
            state: open, closed, or all
            repo_name: Repository name
            limit: Max PRs
            
        Returns:
            List of PR info dicts
        """
        repo = self.get_repo(repo_name)
        prs = []
        
        for pr in repo.get_pulls(state=state)[:limit]:
            prs.append({
                "number": pr.number,
                "title": pr.title,
                "state": pr.state,
                "user": pr.user.login,
                "created_at": pr.created_at.isoformat(),
                "updated_at": pr.updated_at.isoformat(),
                "url": pr.html_url,
                "mergeable": pr.mergeable,
            })
        
        return prs
    
    def review_pr(
        self,
        pr_number: int,
        repo_name: Optional[str] = None,
        auto_approve: bool = False,
    ) -> PRReview:
        """
        Review a pull request.
        
        Args:
            pr_number: PR number
            repo_name: Repository name
            auto_approve: If True, approve if checks pass
            
        Returns:
            PRReview object
        """
        pr = self.get_pr(pr_number, repo_name)
        
        # Get PR diff
        files = pr.get_files()
        
        issues = []
        suggestions = []
        security_findings = []
        
        # Analyze each file
        for file in files:
            if file.status == 'removed':
                continue
            
            # Check for common issues
            content = file.patch
            
            # Security checks
            if 'password' in content.lower() and '=' in content:
                security_findings.append(f"Hardcoded password in {file.filename}")
            
            if 'api_key' in content.lower() and '=' in content:
                security_findings.append(f"Hardcoded API key in {file.filename}")
            
            # Quality checks
            if len(file.patch.split('\n')) > 500:
                issues.append(f"Large file change: {file.filename} (>500 lines)")
            
            # Suggestions
            if 'TODO' in content or 'FIXME' in content:
                suggestions.append(f"Address TODO/FIXME in {file.filename}")
        
        # Calculate quality score
        quality_score = 10.0
        quality_score -= len(issues) * 1.0
        quality_score -= len(security_findings) * 3.0
        quality_score -= len([s for s in suggestions if 'TODO' in s]) * 0.5
        quality_score = max(0.0, min(10.0, quality_score))
        
        # Generate summary
        summary = f"""
PR #{pr.number}: {pr.title}

**Changes:**
- {pr.changed_files} files changed
- {pr.additions} additions
- {pr.deletions} deletions

**Quality Score:** {quality_score:.1f}/10.0

**Files Modified:**
"""
        
        for file in files[:10]:  # Show first 10
            summary += f"- `{file.filename}` ({file.status})\n"
        
        if len(files) > 10:
            summary += f"...and {len(files) - 10} more\n"
        
        if security_findings:
            summary += "\n⚠️ **Security Findings:**\n"
            for finding in security_findings:
                summary += f"- {finding}\n"
        
        if issues:
            summary += "\n📋 **Issues:**\n"
            for issue in issues:
                summary += f"- {issue}\n"
        
        if suggestions:
            summary += "\n💡 **Suggestions:**\n"
            for suggestion in suggestions:
                summary += f"- {suggestion}\n"
        
        ready_to_merge = (
            quality_score >= 7.0 and
            len(security_findings) == 0 and
            pr.mergeable is not False
        )
        
        return PRReview(
            pr_number=pr_number,
            repo=repo_name or self.config.default_repo or "",
            summary=summary,
            issues=issues,
            suggestions=suggestions,
            security_findings=security_findings,
            quality_score=quality_score,
            ready_to_merge=ready_to_merge,
        )
    
    # =========================================================================
    # ISSUES
    # =========================================================================
    
    def create_issue(
        self,
        title: str,
        body: str,
        labels: Optional[List[str]] = None,
        repo_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a new issue.
        
        Args:
            title: Issue title
            body: Issue description
            labels: Labels to add
            repo_name: Repository name
            
        Returns:
            Issue info dict
        """
        repo = self.get_repo(repo_name)
        
        issue = repo.create_issue(
            title=title,
            body=body,
            labels=labels or [],
        )
        
        return {
            "number": issue.number,
            "title": issue.title,
            "url": issue.html_url,
            "state": issue.state,
            "labels": [l.name for l in issue.labels],
        }
    
    def get_issue(self, issue_number: int, repo_name: Optional[str] = None) -> Issue:
        """Get issue by number."""
        repo = self.get_repo(repo_name)
        return repo.get_issue(issue_number)
    
    def list_issues(
        self,
        state: str = "open",
        repo_name: Optional[str] = None,
        labels: Optional[List[str]] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        List issues.
        
        Args:
            state: open, closed, or all
            repo_name: Repository name
            labels: Filter by labels
            limit: Max issues
            
        Returns:
            List of issue info dicts
        """
        repo = self.get_repo(repo_name)
        issues = []
        
        kwargs = {"state": state}
        if labels:
            kwargs["labels"] = labels
        
        for issue in repo.get_issues(**kwargs)[:limit]:
            issues.append({
                "number": issue.number,
                "title": issue.title,
                "state": issue.state,
                "user": issue.user.login,
                "created_at": issue.created_at.isoformat(),
                "labels": [l.name for l in issue.labels],
                "url": issue.html_url,
            })
        
        return issues
    
    def close_issue(
        self,
        issue_number: int,
        repo_name: Optional[str] = None,
        comment: Optional[str] = None,
    ) -> bool:
        """
        Close an issue.
        
        Args:
            issue_number: Issue number
            repo_name: Repository name
            comment: Optional closing comment
            
        Returns:
            True if successful
        """
        issue = self.get_issue(issue_number, repo_name)
        issue.edit(state="closed")
        
        if comment:
            issue.create_comment(comment)
        
        return True
    
    # =========================================================================
    # UTILITY
    # =========================================================================
    
    def get_user_info(self) -> Dict[str, Any]:
        """Get current user info."""
        return {
            "login": self.user.login,
            "name": self.user.name,
            "email": self.user.email,
            "company": self.user.company,
            "location": self.user.location,
            "repos": self.user.public_repos,
            "followers": self.user.followers,
            "following": self.user.following,
        }


# Convenience function
def create_github_client(
    token: str,
    username: Optional[str] = None,
    default_repo: Optional[str] = None,
) -> GitHubClient:
    """
    Create GitHub client.
    
    Args:
        token: GitHub personal access token
        username: GitHub username
        default_repo: Default repository (user/repo)
        
    Returns:
        GitHubClient instance
    """
    config = GitHubConfig(
        token=token,
        username=username,
        default_repo=default_repo,
    )
    
    return GitHubClient(config)