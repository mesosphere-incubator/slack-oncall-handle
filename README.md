This script is supposed to be run at least every 12 hours after 9am
and 9pm PST.  The script will call PagerDuty to determine the given on-call
primary and secondary at that moment.  This will then call Slack and transform
the primary/secondary's names into Slack IDs.  These IDs will
be placed into the given Slack usergroup.

Requires python2 and the requests module.
