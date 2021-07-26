import requests
import os
import json
from dotenv import load_dotenv

load_dotenv()

REDMINE_DOMAIN = os.getenv('REDMINE_DOMAIN')
REDMINE_API_TOKEN = os.getenv('REDMINE_API_TOKEN')
REDMINE_PROJECT_NAME = os.getenv('REDMINE_PROJECT_NAME')

GITEA_DOMAIN = os.getenv('GITEA_DOMAIN')
GITEA_API_TOKEN = os.getenv('GITEA_API_TOKEN')
GITEA_REPO = os.getenv('GITEA_REPO')
GITEA_ENDPOINT = f'api/v1/repos/{GITEA_REPO}/issues'


def process_issues() -> None:
    issues = get_issues()
    labels = get_labels()

    for issue in issues:
        create_issue(issue, labels)


def get_issues(limit: int = 10, offset: int = 0) -> dict:
    """Get issues from the Redmine instance.

    Args:
        limit (int, optional): Limit the number of issues returned. Defaults to 10.
        offset (int, optional): Offset for pagination of issues. Defaults to 0.

    Returns:
        dict: Issues with data in key-value pairs.
    """
    headers = {
        'accept': 'application/json',
        'X-Redmine-API-Key': f'{REDMINE_API_TOKEN}',
        'Content-Type': 'application/json',
    }

    response = requests.get(f'https://{REDMINE_DOMAIN}/projects/{REDMINE_PROJECT_NAME}/' +
        f'issues.json?status_id=*&limit={limit}&offset={offset}', headers=headers)

    return json.loads(response.content)['issues']


def to_username(name: str) -> str:
    """Converts a name to username for simple cases.

    Args:
        name (str): The full name of a member.

    Returns:
        str: The user's username
    """
    name_split = name.split(' ')
    firstletter = name_split[0][0]
    tussenvoegsel = name_split[1:-1][0][0] if len(name_split) > 2 else ''
    lastname = ''.join(name_split[-1])

    return (firstletter + tussenvoegsel + lastname).lower()


def get_labels() -> dict:
    """Get the labels used for the repo in Gitea.

    Returns:
        dict: Pairs of (name, id) of all labels.
    """
    result = {}
    headers = {
        'accept': 'application/json',
        'Authorization': f'token {GITEA_API_TOKEN}',
        'Content-Type': 'application/json',
    }

    response = requests.get(f'https://{GITEA_DOMAIN}/api/v1/repos/{GITEA_REPO}/labels', headers=headers)

    for label in json.loads(response.content):
        result[label['name']] = label['id']

    return result


def create_issue(issue: dict, labels: dict) -> None:
    """Creates an issue in Gitea given the json data of Redmine's API.

    Args:
        issue (dict): The data of the issue from Redmine.
        labels (dict): The labels of the repo in Gitea.
    """
    id = issue['id']
    subject = issue['subject']
    description = issue['description'].replace('\r\n', '\n')
    status = issue['status']['name']
    custom_fields = [f'| {x["name"]} | {x["value"]} |' for x in issue['custom_fields'] if x['value'] != '']
    issue_type = issue['tracker']['name']
    priority = issue['priority']['name']
    is_private = issue['is_private']
    done_ratio = issue['done_ratio']
    category = '-'
    url = f'https://{REDMINE_DOMAIN}/issues/{id}'

    if 'category' in issue:
        category = issue['category']

    assigned_to = '-'
    if 'assigned_to' in issue:
        assigned_to = issue['assigned_to']['name']
        assigned_to_username = to_username(assigned_to)

    author = issue['author']['name']
    author_username = to_username(author)

    if is_private:
        return

    body = f"""## Description
{description}

## Imported from Redmine
| Property      | Value             |
| ---           | ---               |
| ID            | [{id}]({url})     |
| Priority      | {priority}        |
| Status        | {status}          |
| Issue type    | {issue_type}      |
| Author        | {author}          |
| Assigned to   | {assigned_to}     |
| Fields        | {custom_fields}   |
| Category      | {category}        |
| Progress      | {done_ratio}%     |
"""
    if len(custom_fields) > 0:
        body += '\n'.join(custom_fields)

    headers = {
        'accept': 'application/json',
        'Authorization': f'token {GITEA_API_TOKEN}',
        'Content-Type': 'application/json',
    }

    data = {
        "title": subject,
        "body": body,
        "closed": status in ['Resolved', 'Closed', 'Rejected'],
    }

    if assigned_to != '-':
        data['assignee'] = assigned_to_username

    issue_type_map = {
        'Bug': 'bug',
        'Feature': 'enhancement',
        'Support': 'support',
    }
    data['labels'] = [labels[issue_type_map[issue_type]]]

    if status == 'Rejected':
        data['labels'].append('wontfix')

    print(subject)

    response = requests.post(
        f'https://{GITEA_DOMAIN}/{GITEA_ENDPOINT}?sudo={author_username}',
        headers=headers,
        data=json.dumps(data)
    )

    if not response.ok:
        SystemExit()


process_issues()
