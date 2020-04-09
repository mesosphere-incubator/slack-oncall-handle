#!/usr/bin/env python
import json
import os
import requests
import sys

"""
This script is supposed to be run at least every 12 hours after 9am
and 9pm PST.  The script will call PagerDuty to determine the given on-call
primary and secondary at that moment.  This will then call Slack and transform
the primary/secondary's names into Slack IDs.  These IDs will
be placed into the given Slack usergroup.

Requires python2 and the requests module.
"""

PAGERDUTY_APIKEY = os.getenv('PAGERDUTY_APIKEY')
PAGERDUTY_ONCALL_ESCALATION = os.getenv('PAGERDUTY_ONCALL_ESCALATION')
PAGERDUTY_API_ONCALL = os.getenv('PAGERDUTY_API_ONCALL', 'https://api.pagerduty.com/oncalls?include[]=users&escalation_policy_ids[]=')
PAGERDUTY_ONCALL_URI = PAGERDUTY_API_ONCALL + PAGERDUTY_ONCALL_ESCALATION

SLACK_APIKEY = os.getenv('SLACK_APIKEY')
SLACK_USERS_URI = 'https://mesosphere.slack.com/api/users.list?token=%s&cursor=%s'

SLACK_USERGROUP_ID = os.getenv('SLACK_USERGROUP_ID')
SLACK_ORG_URL = os.getenv('SLACK_ORG_URL', "https://mesosphere.slack.com")
SLACK_USERGROUP_URI = '%s/api/usergroups.users.update?token=%s&usergroup=%s&users=%s'

def transform_pagerduty_results(results):
    """Filters the PagerDuty API results to a subset of fields we care about."""
    transform = []

    for entry in results['oncalls']:
        transform.append({
            'name'  : entry['user']['name'],
            'email' : entry['user']['email'],
            'level' : entry['escalation_level'],
            'start' : entry['start'],
            'end'   : entry['end']
        })

    return transform

def get_slack_id(members, person):
    """Takes the list of slack members and returns the ID of the person."""
    for member in members:
        name_match = 'real_name' in member['profile'] and person['name'] == member['profile']['real_name']
        email_match = 'email' in member['profile'] and person['email'] == member['profile']['email']

        if not member['deleted'] and not member['is_restricted'] and (name_match or email_match):
            return member['id']

    return None

if __name__ == '__main__':
    if not PAGERDUTY_APIKEY \
        or not PAGERDUTY_ONCALL_ESCALATION \
        or not SLACK_APIKEY \
        or not SLACK_USERGROUP_ID:
        print("Missing environment variable: 'PAGERDUTY_APIKEY', 'SLACK_APIKEY', or 'SLACK_USERGROUP_ID'")
        sys.exit(1)

    # The PagerDuty on-call API is paginated, but we filter by escalation policy.
    # This script does not expect there to be more than 25 results (the default
    # number of results from the API call), and will error if this ever happens.
    print(PAGERDUTY_ONCALL_URI)
    r = requests.get(PAGERDUTY_ONCALL_URI,
        headers={
            'Authorization': 'Token token=%s' % PAGERDUTY_APIKEY,
            'Accept': 'application/vnd.pagerduty+json;version=2'
        })
    r = r.json()


    # Filter down to a smaller subset of data.
    possible_oncalls = transform_pagerduty_results(r)

    if r['more']:
        print("Number of PagerDuty oncalls exceed 25; This schedule may be configured improperly")
        sys.exit(1)

    print("Found the following on-call for Escalation Policy: '%s'" % PAGERDUTY_ONCALL_ESCALATION)
    print(json.dumps(possible_oncalls, indent=2))

    # Grab the primary and secondary.
    primary = [user for user in possible_oncalls if user['level'] == 1]
    secondary = [user for user in possible_oncalls if user['level'] == 2]

    # When there is more than one on-call for a given level, prioritize
    # the last person to start the on-call rotation.  If there are
    # people permanently assigned to a given level, they will be deprioritized
    # in this case (including non-persons like '*-oncall@mesosphere.io' emails).
    if len(primary) > 1:
        primary.sort(key=lambda user: user['start'])
        primary = [primary[len(primary) - 1]]

    if len(secondary) > 1:
        secondary.sort(key=lambda user: user['start'])
        secondary = [secondary[len(secondary) - 1]]

    print("Primary:")
    print(json.dumps(primary, indent=2))
    print("Secondary:")
    print(json.dumps(secondary, indent=2))

    # Grab the user list from Slack.
    got_all_users = False
    users = []
    next_cursor = ""
    while got_all_users is False:
        r = requests.get(SLACK_USERS_URI % (SLACK_APIKEY, next_cursor))
        r= r.json()
        if 'members' in r.keys():
            users += r['members']

        if 'response_metadata' in r.keys() and r['response_metadata'] != "":
            next_cursor = r['response_metadata']['next_cursor']
        else:
            got_all_users = True

    primary = get_slack_id(users, primary[0])
    print(users[0])

    # There might not be a secondary.
    # But there should always be a primary.
    if len(secondary) > 0:
        secondary = get_slack_id(users, secondary[0])
    else:
        secondary = None

    print("Primary:")
    print(json.dumps(primary, indent=2))
    print("Secondary:")
    print(json.dumps(secondary, indent=2))

    if not primary or not secondary:
        print("Uh oh, couldn't find both on-calls in Slack")

    # Change the user group.
    slackrequesturi = SLACK_USERGROUP_URI % (SLACK_ORG_URL, SLACK_APIKEY, SLACK_USERGROUP_ID, '%s,%s' % (primary, secondary))
    print(slackrequesturi)
    r = requests.post(slackrequesturi)
    print(json.dumps(r.json(), indent=2))
