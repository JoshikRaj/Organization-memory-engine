from src.ingestion.jira_ingestor import fetch_jira_issues
data = fetch_jira_issues(start_at=0, max_results=2)
data.keys()
data["issues"][0]["key"]