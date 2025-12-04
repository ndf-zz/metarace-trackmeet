# Trackmeet "Data Bridge" Schema

*Updated: 2025-12-04*


## Overview

Trackmeet data bridge is a loose collection of data objects
that convey information about a meet, competitions, competitors
and results for overlay on graphic displays. All data endpoints are
communicated as JSON-encoded objects, via MQTT (telegraph)
or HTTP.


## Definitions

   - Meet: A whole championship is considered a single "meet".
     A meet comprises several sessions of events which together
     determine results for a number of competitions over a
     set of competitor categories.
   - Competition: A type of race or award for which there is a prize
     at the meet. Eg: Scratch Race, Points Race, Individual Pursuit, Sprint
   - Competitor: A single rider, a Madison pair or a team of riders. [1]
   - Category: A competitor's category
     Eg: ME "Men Elite", WE "Women Elite", MJ "Men Junior",
     PARA "Para-cycling", M15 "Men Under 15", W17 "Women Under 17" [2,3]
   - Phase: Within a competition, phases progress competitors
     toward a final result. The final phase of a competition
     will be labelled "Final" in the subtitle. [4,5]
   - Contest: Where a phase of competition requires more than one
     result to decide the outcome, each result is assigned a contest.
     Eg: "Sprint at 10 laps to go" for a points race or
     "1-6 Final" for a Keirin. [5]
   - Heat: If a contest requires more than one outcome to determine
     the result, each individual outcome will be decided by a heat [5,6]
   - Path: A slash delimited list identifying a meet, category,
     competition, phase, contest, and heat. [5,6]
   - Startlist: A list of competitors and their qualifying information
     (where relevant) that will be expected to start a
     competition fragment.
   - Result: A summary of the outcomes of a competition fragment,
     or a virtual standing if the result is partially determined.
   - Event: A heat, contest or phase on the meet schedule
     identified uniquely by a short string, usually numeric. Eg:
     38 "Event 38: W15 Sprint Semi Final Heat 3, if required"
     An event may reference more than one specific path, and include
     multiple competition fragments.
   - Fragment: A competition, phase, contest or heat.
   - Session: An ordered list of events to be held sequentially as part of
     the meet, identified by a short string, usually numeric.
     Eg: 1 "Day 1, Morning Session" [7]
   - Schedule of events: An ordered list of sessions that make up the
     entire meet.
   - Index of events: A mapping between event IDs, sessions and 
     the associated category, competition, phase and fragments.
   - Current event: The event ID and unique meet path for the current
     action on the track and its associated competition fragment.
   - Home Straight: The home straight is on the same side as the finish line.
   - Back Straight: The back straight is on the opposite side to
     the home straight.
   - A/B Competitor: For timed events with two competitors on the track
     (pursuit, time trial, team sprint, team pursuit) The "A"
     competitor refers to the home straight, and "B" to the back
     straight. A/B finish lines are marked with a half-length white line
     positioned in the middle of the respective straight.
   - Place/Placing: A competitor that completes an event, or that is
     assigned a finish, will be allocated a placing by officials. Placed
     competitors are ranked according to their assigned places.
   - Ranking: Order (number) of a competitor's result in an event. [8]
   - Classification: A competition overall result (eg "Sprint Final
     Classification") or a result assigned to a competitor in an event.
     For a placed competitor, this will be a place number with a
     trailing period (eg 1. 3. 21.) or in-text an ordinal number (eg 1st,
     2nd, 3rd etc). Unplaced competitors will be classified as non-starters,
     non-finishers, abandoned or disqualified with a classification code:
     dns, dnf, abd, dsq (respectively).
   - Relegation: A competitor's placing may be altered due to
     conduct in the event, usually to last place in the heat/contest.
     A relegation does not disqualify a competitor, and there may be
     no mention in the result why the relegation occurred.
   - Medals: The 1st, 2nd and 3rd placed competitors in a competition
     will be awarded Gold, Silver and Bronze medals (respectively).
   - Title/Champion: The best-placed Australian competitor in a
     competition will be awarded the Australian title. Eg:
     Elite Men Sprint Australian Champion.

Notes:

   1. Competition type determines whether competitors are riders,
      pairs or teams.
   2. Para-cyclists will be assigned an additional sport class
      based on impairment, eg MC2 "Men Cycle 2", WB "Women Tandem",
      multiple sport classes may be present in a single competition.
   3. Tandem para-cyclists are individual competitors with an
      associated pilot rider. Pilot details are usually displayed
      on results and startlists immediately under the rider. A pilot's
      competitor ID is the same as their rider.
   4. Any competition with one or more events on the meet schedule
      will have at least one phase.
   5. Where phases, contests or heats do not apply to a competition,
      they are omitted. A competition with no events or one that
      is determined by other means will have no phases.
   6. Phases of competition with heats but no contests will have their
      heat field collapsed into contest. In that case, the contests
      will be labelled as heats. Eg: 2024atc/ME/ip/qualifying/3 "Men Elite
      Individual Pursuit Qualifying Heat 3"
   7. Warm-ups, breaks and presentations may be included as
      session entries, but they will not reference a path in the meet.
   8. All competitors present in a result are assigned a ranking,
      even if currently not classified. Rankings may not
      align exactly with places, and they may be duplicated.
      The order of display of result lines is provided by the
      array structure in the result object.


## Display Conventions

Cycling startlists and results should adhere to the following conventions:

   - Rider last (family) name should be presented all uppercase.
   - Rider first (given) name should be presented mixed case.
   - For Australian events, names should be presented First LAST.
   - Classifications are left-aligned and will always have a trailing period
     eg: '1.', '2.' unless they are one of the special values:
     'dns', 'dnf', 'abd' or 'dsq'.
   - A virtual classification, eg during qualifying or for an intermediate
     time split should be surrounded with parentheses: (3.), italicised: *3.*,
     or formatted in such a way that is is obviously not a confirmed place.
     Places are confirmed when then fragment status is 'provisional' or
     'final'.
   - **Rider numbers should never be displayed with a trailing period.**
     When displayed in a column, they should be right-aligned.
   - The "number" column on team results should be omitted to
     simplify readability. Team competitor IDs are for internal
     reference only.
   - Result times, down times, points should be right-aligned
   - State affiliations are shown in parentheses () next to a
     rider name, and may be omitted for space.
   - Where an event includes additional information, it should be
     included in a right-aligned column to the left of the result column

Result based on time:

	1.  234 Amanda HUGGINKISS (VIC)     59.710
	2.   12 Oliver SUDDEN (NSW)       1:00.211
	dns  17 Charlie SAYNJELS (NT)

Team result:

	1.  Victoria Team 1               1:23.456
	2.  New South Wales Team 4        1:23.661

Elimination Standing:

	(14.)   5 Another RIDERGUY (NSW)
	(15.)  12 Claud YOUREYESOUT (WA)

Para event with multiple sport classes:

	1.    7 Andover VIST (VIC)     WC4  1:32.456
	2.   22 Matt O'HAWN (NSW)      MC2  1:22.551
	3.   31 Roe D'ABOOT (QLD)       MB    59.319
	        Steier D'ABOOT (QLD) Pilot
	4.   41 Anne TEAK (WA)          WB    59.992
	        Inna SHAAR (WA)      Pilot


## Meet Path Reference


### Endpoint Summary

   - [MEET]: Meet information, list of sessions and list of categories
   - [MEET]/events: Index of events
   - [MEET]/current: Current event information
   - [MEET]/current/startlist: Startlist for current fragment [TBC]
   - [MEET]/current/result: Result for current fragment [TBC]
   - [MEET]/[SESSION]: Session information
   - [MEET]/[CATEGORY]:
     Competitor category overview and competitions in meet
   - [MEET]/[CATEGORY]/competitors:
     Rider, team and pilot labels
   - [MEET]/[CATEGORY]/[COMPETITION]:
     Competition information, list of phases, record information
   - [MEET]/[CATEGORY]/[COMPETITION]/startlist:
     Startlist for overall competition
   - [MEET]/[CATEGORY]/[COMPETITION]/result:
     Final overall result for competition
   - [MEET]/[CATEGORY]/[COMPETITION]/[PHASE]:
     Competition phase summary and list of contests
   - [MEET]/[CATEGORY]/[COMPETITION]/[PHASE]/startlist:
     Startlist for competition phase
   - [MEET]/[CATEGORY]/[COMPETITION]/[PHASE]/result:
     Result for competition phase
   - [MEET]/[CATEGORY]/[COMPETITION]/[PHASE]/[CONTEST]:
     Contest summary and list of heats
   - [MEET]/[CATEGORY]/[COMPETITION]/[PHASE]/[CONTEST]/startlist:
     Startlist for contest
   - [MEET]/[CATEGORY]/[COMPETITION]/[PHASE]/[CONTEST]/result:
     Result for contest
   - [MEET]/[CATEGORY]/[COMPETITION]/[PHASE]/[CONTEST]/[HEAT]:
     Heat summary
   - [MEET]/[CATEGORY]/[COMPETITION]/[PHASE]/[CONTEST]/[HEAT]/startlist:
     Startlist for heat
   - [MEET]/[CATEGORY]/[COMPETITION]/[PHASE]/[CONTEST]/[HEAT]/result:
     Result for heat

### Path Endpoint Types

Data endpoints map to a JSON encoded object, with 
keys specific to the relevant type. All path endpoints
also include a serial number and last updated field:

key | type | descr
--- | --- | ---
serial | integer | Endpoint serial number
updated | 8601DT | Date and time of last update

These keys are omitted from examples below for clarity.

#### [MEET]

The meet object is a top level identifier.
It contains string information about the organisation,
date summary, president of the commissaires'
panel (PCP), a list of sessions and a list of categories.

key | type | descr
--- | --- | ---
title | string | Meet title
subtitle | string | Meet subtitle
organiser | string | Meet organiser
location | string | Meet location
locationCode | string | Venue code (TBC)
pcp | string | Name of the president of the commissaires' panel (PCP)
date | string | Description of event dates
timezone | string | Zoneinfo key for meet location
startDate | 8601D | Date of first day of competition
endDate | 8601D | Date of last day of competition
schedule | object | Mapping of session ids to session labels
categories | object | Mapping of category ids to labels

Example:

	2025atc
	{
	 "title": "AusCycling Track National Championships",
	 "subtitle": "Junior, Under 19, Elite and Para-Cycling",
	 "organiser": "AusCycling",
	 "location": "Anna Meares Velodrome, Brisbane",
	 "pcp": "Wayne Pomario",
	 "date": "March 22-30, 2025",
	 "timezone": "Australia/Brisbane",
	 "startDate": "2025-03-22",
	 "endDate": "2025-03-30",
	 "schedule": {"1":"Session 1", "2":"Session 2", ...
	 "categories": {"W15":"Women Under 15", "M15":...
	}

Subtopics available under [MEET]:

  - events: An event index object for the meet
  - current: A current event object for the action on-track
  - [SESSION]: Session information for session ID
  - [CATEGORY]: Competitor category information

#### [MEET]/events

Map of event ids to their associated information. Each key
in the event index maps to an EVENT object with the
following keys from the schedule of events:

key | type | descr
--- | --- | ---
title | string | Category/Competition title
subtitle | string | Event subtitle
info | string | Phase information string
extra | string | Additional event information eg "Best of 3 Heats"
distance | string | Distance string with units
laps | integer | Lap count where relevant
session | string | Session ID
category | string | Competitor category ID
competition | string | Competition ID
phase | string | Competition phase ID
fragments | array | ordered list of meet paths to fragments in this event
startTime | 8601DT | Rough event start time on the session program

Example:

	2025atc/events
	{
	 "1": {
	  "title": "Men Elite Sprint",
	  "subtitle": "Qualifying",
	  "info": "Top 16 to Round 1",
	  "extra": null,
	  "distance": "200\u2006m",
	  "laps": null,
	  "session": "1",
	  "category": "ME",
	  "competition": "sprint",
	  "phase": "qualifying",
	  "fragments": ["ME/sprint/qualifying"],
          "startTime": ...
	 }, ...
	}

*Note:* Event subtitle, info, extra may not line up
exactly with competition data, event index is informative
and based on content of the published schedule of events.

#### [MEET]/current

Live timing and event data is communicated in the current
event object. All keys will be present in the object, but 
with null value unless they have meaning for the
event context.

key | type | descr
--- | --- | ---
path | string | Meet path for the event fragment currently in progress or null
status | STATUS | Status of result for this fragment
title | string | Category/Competition for this fragment
subtitle | string | Phase... string for this fragment
info | string | Event information from schedule
event | string | Event ID for the current event, break or presentation
session | string | Session ID for the current session
category | string | Category ID
competition | string | Competition ID
phase | string | Competition phase ID
contest | string | Contest ID
heat | string | Heat ID
competitorType | string | Competitor type indicator
competitionType | string | Competition type indicator
eventStart | 8601DT | Rough start time for start of event
startTime | 8601DT | Rolling clock start time
endTime | 8601DT | Rolling clock end time
competitorA | RESULTLINE | "A" Competitor (pursuit, tt, 200)
labelA | string | Text prefix for "A" split (pursuit, tt, 200, mass start)
timeA | 8601I | Elapsed time for "A" split (pursuit, tt, 200, mass start)
downA | 8601I | Down time for "A" split (pursuit, tt, 200)
rankA | integer | Ranking or standing for "A" split (pursuit, tt, 200)
infoA | string | Informative string: catch, caught, abandon, false-start
competitorB | RESULTLINE | "B" Competitor (pursuit, tt)
labelB | string | Text prefix for "B" split or elapsed time (pursuit, tt)
timeB | 8601I | Elapsed time for "B" split (pursuit, tt)
downB | 8601I | Down time for "B" split (pursuit, tt)
rankB | integer | Ranking or standing for "B" split (pursuit, tt)
infoB | string | Informative string: catch, caught, abandon, false-start
eliminated | RESULTLINE | Competitor eliminated (Elimination race only)
remain | integer | Number of riders remaining in race (Elimination race only)
toGo | integer | Laps to go (mass start, sprint, 200)
laps | integer | Total laps (mass start, sprint, 200)
distance | string | Event distance label with units eg "2 km", "750 m"
record | RECORD | In the case a competitor betters a record, the record object [DEP]
weather | WEATHER | Current local weather observation if known

Example:

	2025atc/current
	{
	 "path": null,
	 "status": null,
	 "title": "Warm-up 12:00pm - 12:50pm",
	 "subtitle": null,
	 "event": null,
	 ...
	}

#### [MEET]/[SESSION]

Information for session ID [SESSION] and an ordered list of events

key | type | descr
--- | --- | ---
title | string | Meet title
subtitle | string | Meet subtitle
location | string | Meet location
label | string | Text label for session
startTime | 8601DT | Session start time
endTime | 8601DT | Estimated session end time
events | object | Mapping of event IDs to Schedule labels
finals | object | Mapping of CAT/COMP ids to competition title

Example:

	2025atc/1
	{
	 "title": "AusCycling Track National Championships",
	 "subtitle": "Junior, Under 19, Elite and Para-Cycling",
	 "location": "Anna Meares Velodrome, Brisbane",
	 "label": "Session 1",
	 "startTime": "2025-03-24T13:00:00+10:00",
	 "endTime": "2025-03-24T18:30:00+10:00",
	 "events": {"1": "Men Elite Sprint Qualifying", ...
	 "finals": {"ME/sprint": "Men Elite Sprint", ...
	}

#### [MEET]/[CATEGORY]

Information on the meet category with ID [CATEGORY]

key | type | descr
--- | --- | ---
label | string | Text label for category eg "Men Elite"
competitions | object | Mapping of competition codes to labels

Subtopics available under [CATEGORY]:

  - competitors: Rider, team, pairs and pilots in category.
  - [COMPETITION]: Information on competition with ID [COMPETITION]

Example:

	2025atc/W15
	{
	 "Women Under 15",
	 "competitions": {"ip": "Individual Pursuit"...
	}

#### [MEET]/[CATEGORY]/competitors

List of riders, teams, pairs and pilots

key | type | descr
--- | --- | ---
riders | object | Map of rider IDs to RIDER objects
teams | object | Map of team IDs to TEAM objects
pairs | object | Map of competitor IDs to Madison PAIR objects
pilots | object | Map of rider IDs to their associated pilot RIDER

Example:

	2025atc/W15/competitors
	{
	 "riders": {
	  "1": { "number": "1", "class": null, "first": "Amanda", ...  },
	  ...
	 },
	 "teams": {
	  "VIC1": { "code": "VIC1", "name": "Victoria Team 1", ... },
	  ...
	 },
	 "pairs": null,
	 "pilots": null
	}

#### [MEET]/[CATEGORY]/[COMPETITION]

Competition summary object.

key | type | descr
--- | --- | ---
label | string | Competition string label
competitorType | string | Competitor type indicator
category | string | Competitor category ID
title | string | Category/Competition title eg "Men Elite Sprint"
status | STATUS | Competition overall result status
phases | object | Mapping of phase ids to phase labels
events | object | Map of event IDs in competition to event Labels
warnings | object | Mapping of competitor IDs to warnings
records | object | Mapping of record types to RECORD objects

Subtopics available under [COMPETITION]:

  - startlist: Startlist object for the whole competition
  - result: Overall result for whole competition, including medals
    and national title winner.
  - [PHASE]: Details for the competition phase with ID [PHASE]

Example:

	2025atc/W15/ip
	{
	 "label": "Individual Pursuit",
	 "competitorType": "rider",
	 "category": "W15",
	 "title": "Women Under 15 Individual Pursuit",
	 "status": "virtual",
	 "phases": {"qualifying": "Qualifying", ...
	 "warnings": {},
	 "events": {"1": "Qualifying", ...
	 "records": {"national": {...
	}

#### [MEET]/[CATEGORY]/[COMPETITION]/[PHASE]

Competition phase object.

key | type | descr
--- | --- | ---
title | string | Category/Competition title eg "Men Elite Keirin"
subtitle | string | Phase title eg "Qualifying"
info | string | Event information string
status | STATUS | Phase result status (if known)
contests | object | Map of contest ids to labels
events | object | Map of event ids to event subtitle
distance | string | Event distance and units (if relevant)
laps | integer | Number of laps (if relevant)

Subtopics available under [PHASE]:

  - startlist: Startlist object for the competition phase
  - result: Result for the competition phase
  - [CONTEST]: Details for the contest with ID [CONTEST]

Example:

	2025atc/W15/ip/qualifying
	{
	 "title": "Women Under 15 Individual Pursuit",
	 "subtitle": "Qualifying",
	 "status": "final",
	 "info": "1st & 2nd to Gold final; 3rd & 4th to Bronze final",
	 "contests": ["1", "2", "3", ...
	 "events": ["1"],
	 "laps": 8,
	 "distance": "2000\u2006m"
	}

#### [MEET]/[CATEGORY]/[COMPETITION]/[PHASE]/[CONTEST]

Competition contest object.

key | type | descr
--- | --- | ---
title | string | Category/Competition title eg "Men Elite Keirin"
subtitle | string | Phase/Contest title eg "Round 1 1v16"
label | string | Contest Label
status | STATUS | Contest result status
info | string | Event (phase) information string
heats | object | Map of heat ids to labels
events | object | Map of event ids to event subtitle
distance | string | Event distance and units (if relevant)
laps | integer | Number of laps (if relevant)

Note: For events with heats but without contests, the heats
will collapse into contests, but will be labelled as heats.

Subtopics available under [CONTEST]:

  - startlist: Startlist object for the competition phase
  - result: Result for the competition contest
  - [HEAT]: Details for the heat with ID [HEAT]

Example:

	2025atc/M15/sprint/semi/1v4
	{
	 "title": "Men Under 15 Sprint",
	 "subtitle": "Semi Final - 1v4",
	 "label": "1v4",
	 "status": "provisional",
	 "info": null,
	 "heats": {"1": "Heat 1", ...
	 "events": {"31": ...
	 "laps": 3,
	 "distance": "750\u2006m"
	}

#### [MEET]/[CATEGORY]/[COMPETITION]/[PHASE]/[CONTEST]/[HEAT]

Competition heat object.

key | type | descr
--- | --- | ---
title | string | Category/Competition title eg "Men Elite Keirin"
subtitle | string | Phase/Contest/Heat title eg "1/4 Final - 2v7 Heat 1"
label | string | Heat label eg "Heat 1"
status | STATUS | Heat result status
info | string | Event (phase) information string
events | object | Map of event ids to event subtitle
distance | string | Event distance and units (if relevant)
laps | integer | Number of laps (if relevant)

Subtopics available under [HEAT]:

  - startlist: Startlist object for the competition phase
  - result: Result for the competition contest

Example:

	2025atc/M15/sprint/semi/1v4/2
	{
	 "title": "Men Under 15 Sprint",
	 "subtitle": "Semi Final - 1v4 Heat 2",
	 "label": "Heat 2",
	 "status": "final",
	 "info": null,
	 "events": {"34": ...
	 "laps": 3,
	 "distance": "750\u2006m"
	}

#### .../startlist

A startlist for the parent competition, phase, contest
or heat.

key | type | descr
--- | --- | ---
title | string | Category/Competition title eg "Men Elite Keirin"
subtitle | string | Phase... title eg "1/4 Final 2v7 Heat 1" [TBC]
info | string | Event information string
distance | string | Event distance and units (if relevant)
laps | integer | Event laps (if relevant)
status | STATUS | Status of the startlist
competitionType | string | Indication of the type of startlist
competitorType | string | Indication of the competitor type
competitors | array | Ordered list of STARTER objects

Example:

	2024atc/M17/ip/final/bronze/startlist
	{
	 "title": "Men Under 17 Individual Pursuit",
	 "subtitle": "Bronze Final"
	 "info": null,
	 "distance": "2000\u2006m",
	 "laps": 8,
	 "status": "final",
	 "competitionType": "dual",
	 "competitorType": "rider",
	 "competitors": [
	  { "competitor": "1", "name": "Oliver SUDDEN (WA)",
	    "members": [], "info": null, "badges": [],
	    "qualRank": 3, "qualPlace": "3.", "qualTime": "PT2M24.5660S" }, ...
	 ]
	}

#### .../result

A result for the parent competition, phase, contest
or heat.

key | type | descr
--- | --- | ---
title | string | Category/Competition title eg "Men Elite Keirin"
subtitle | string | Phase... title eg "1/4 Final 2v7 Heat 1" [TBC]
info | string | Event information string
distance | string | Event distance and units (if relevant)
laps | integer | Number of laps (if relevant)
status | STATUS | Status of the result
competitionType | string | Indication of the type of result
competitorType | string | Indication of the competitor type
lines | array | Ordered list of RESULTLINE objects
units | string | Result units if applicable
decisions | array | Ordered list of decisions of the commissaires' panel
weather | WEATHER | Weather observations as at the start of the result
detail | object | Map of competitor IDs and lap IDs to result DETAIL objects
startTime | 8601DT | Date and time of start of this result (if known)

Example:

	2024atc/me/points/final/10/result
	{
	 "title": "Men Elite Points Race",
	 "subtitle": "Sprint at 10 laps to go",
	 "info": null,
	 "distance": null,
	 "laps": null,
	 "status": "provisional",
	 "competitionType": "bunch",
	 "competitorType": "rider",
	 "lines": [
	  { "rank": 1, "class": "1.", "competitor": "23",
	    "name": "Athony RIDERGUY (VIC)", "members": [],
	    "info": null, "badges": ["warning"], "result": "5" }, ...
	 ],
	 "units": "pts",
	 "decisions": ["Rider 23 A. RIDER relegated for irregular sprint"],
	 "detail: {},
	 "startTime": null
	}


## Data Type Reference

### Composite Object types

#### STARTER

Provides information about a starter in an event

key | type | descr
--- | --- | ---
competitor | string | Competitor ID
nation | string | Competitor's nation ID
name | string | Competitor's formatted name string
pilot | string | Competitor's pilot name if relevant
members | array | ordered list of rider IDs in team [TBC]
info | string | Seeding, handicap, sport class or draw indicator
badges | array | Array of badges relevant to competitor in this startlist
qualRank | integer | Ranking in qualification phase
qualPlace | string | Placing in qualification phase
qualTime | 8601I | Recorded time in qualification phase

#### RESULTLINE

Provides a single line in an event result or ranking

key | type | descr
--- | --- | ---
rank | integer | Competitor's ranking in this result
class | string | Competitor's classification or standing in this result
competitor | string | Competitor ID
nation | string | Competitor's nation ID
name | string | Competitor's formatted name string
pilot | string | Competitor's pilot name if relevant
members | array | ordered list of rider IDs in team [TBC]
info | string | Optional additional information string for this result line
badges | array | Array of badges relevant to competitor in this result
result | string | Formatted text result string
extra | string | Additional result info string (eg down time)

#### DETAIL

A split lap or sprint lap detail with the following structure:

key | type | descr
--- | --- | ---
label | string | Label for this split/sprint
rank | integer | Competitor's ranking at this split - may be null
elapsed | 8601I | Elapsed time to this split/sprint (if known)
interval | 8601I | Interval since previous split/sprint (if known)
points | numeric | Points awarded to competitor at this sprint

Example for a 100m split in a flying 200m time trial:

	{
	 "label": "100\u2006m",
	 "rank": 2,
	 "elapsed": "PT5.618S",
	 "interval": "PT5.618S",
	 "points": null
	}


*Note:* Due to rounding, the sum of split intervals
may not equal elapsed time.


#### RIDER

RIDER objects provide information on an individual rider

key | type | descr
--- | --- | ---
number | string | Competitor ID
class | string | Sport class ID (PARA riders) or Category (all others)
first  | string | Rider first name
last   | string | Rider last name
nation | string | IOC 3 letter nation code
uciid  | string | UCI 11 digit unique identifier or null if not known
dob    | 8601D | Date of birth
state  | string | State of rider's Australian club or null if not known
org    | string | Club, team or organisation string


#### TEAM

TEAM objects provide a name and set of possible members. Note that
riders taking the start will be indicated in the specific heat or
contest startlist.

key | type | descr
--- | --- | ---
code | string | Competitor ID
name | string | Team name
nation | string | IOC 3 letter nation code
state | string | Team state of origin if known
members | array | Ordered list of rider IDs eligible to participate in team


#### PAIR

Madison competitor PAIR object. When listed, the black rider
should be displayed before the red rider.

key | type | descr
--- | --- | ---
number | string | Competitor ID
name | string | String name for pairing
nation | string | IOC 3 letter nation code
state | string | Competitor state (if valid)
black | string | Competitor ID of rider carrying black number
red | string | Competitor ID of rider carrying red number


#### WEATHER

Local weather observation.

key | type | descr
--- | --- | ---
t | number | Temperature in degrees Celsius
h | number | Relative humidity percentage
p | number | Atmospheric pressure in hectopascals (hPa)


#### RECORD

*Note:* Record data TBC

Record data for a [CATEGORY]/[COMPETITION]. A competitor beating
a current record is announced as having bettered the record. A new
record is not set until after the effort has been ratified by
officials and extra conditions met. Records are provided in the
[COMPETITION] object as a mapping between record type label
and a RECORD object.

key | type | descr
--- | --- | ---
class | string | Sport class ID (PARA riders) or Category (all others)
title | string | [CATEGORY]/[COMPETITION]/[PHASE] title 
subtitle | string | Record type information: "World", "National", "All Comers"
distance | string | Record distance label with units eg "2 km", "750 m"
record | 8601I | Record time
date | 8601D | Date record was bettered
place | string | Location record was bettered (usually city)
country | string | IOC country code of nation where record was bettered
nation | string | IOC country code of competitor holding record
name | string | Name of competitor holding record
pilot | string | Pilot name for tandem competitors
members | array | Ordered set of team members if competitor was team


### JSON data types

   - string: Unicode string
   - integer: Integral numeric value
   - number: Numeric value (double precision float)
   - bool: Boolean value True/False
   - array []: Ordered list of objects
   - object {}: Collection of name-value pairs
   - null: Empty value

### Schema-specific data types and labels

   - decimal: Exact decimal value with precision represented as a string[2]
     eg: "0.1234" === 1234/10000
   - 8601D: ISO8601(4.1.2.2) Date string
     eg: "1996-02-27"
   - 8601DT: ISO8601(4.3.2) Date and time of day string
     eg: "2022-11-01T09:10:11.234567+11:00"
   - 8601I: ISO8601(4.4.1b) Time interval string, with optional
     (non-standard) sign prefix: eg: "-PT1H23M12.345S"
   - STATUS: Result status indicator one of:
       - null: Event has not yet started
       - "virtual": Event has begun, rankings indicate a standing only
       - "hold": Starters/Rankings are virtual, pending review by officials
       - "provisional": Event has finished and places have been assigned
       - "final": Places have been approved by officials, result is finalised
   - Valid competitor type indicators:
       - null: Competitor type is not relevant, or unknown
       - "rider": Individual riders
       - "team": Teams of riders (team pursuit, team sprint)
       - "pair": Black/Red pair (Madison)
   - Example competition type labels:
       - null: Competition type is not relevant
       - "sprint": Sprint
       - "ip": Individual Pursuit
       - "tp": Team Pursuit
       - "tt": Time Trial
       - "points": Points Race
       - "keirin": Keirin
       - "ts": Team Sprint
       - "madison": Madison
       - "scratch": Scratch Race
       - "elimination": Elimination Race
   - Para-cycling sport class labels (16.4.003):
       - "MB"
       - "WB"
       - "MC1"
       - "WC1"
       - "MC2"
       - "WC2"
       - "MC3"
       - "WC3"
       - "MC4"
       - "WC4"
       - "MC5"
       - "WC5"
   - Startlist/result competition type labels:
       - "single": Single competitor in each heat (tt, 200)
       - "dual": A/B competitors (tt, pursuit, team sprint, team pursuit)
       - "bunch": Mass start (scratch, points etc)
       - "classification": Final classification for a competition - includes
         medals and champion badges when relevant. May include lower
         places before finals are complete.
       - null: Listing does not have a specific type
   - Badges:
       - "warning": Competitor has received a warning in the
         current competition, indicated with a yellow card.
       - "disqualified": Competitor was disqualified from the current
         competition, indicated with a red card.
       - "qualified": Competitor has qualified for the next phase
         of the current competition in this result, indicated with
         a stylised **Q** or a green flag.
       - "win": Competitor has recorded a win in the current contest.
         Indicated with an asterisk or green flag - applies to sprint
         best of 3 heats and is usually shown on both startlist and result.
       - "rel": Competitor was relegated by officials in current result,
         a reason may be provided in the decisions object.
       - "gold": Competitor was awarded gold medal.
       - "silver": Competitor was awarded silver medal.
       - "bronze": Competitor was awarded bronze medal.
       - "champion": Competitor was awarded national championship/title,
         usually indicated with a small jersey in the Australian colours.
       - "chr": Competitor recorded a time better than championship record.
       - "acr": Competitor recorded a time better than an all comers record.
       - "nr": Competitor recorded a time better than current national record.
       - "wr": Competitor recorded a time better than current world record.
   - Record type labels:
       - "national": Best time set by an Australian anywhere in the world
       - "allcomers": Best time set in Australia by any nationality
       - "championship": Best time set by an Australian at an
         Australian Championship
       - "world": Current UCI world record

Notes:

   1. Numeric values intended for display on screen are
      communicated as string encoded decimal numbers with
      an explicit precision. Unwanted precision may be removed
      by truncation. Extra precision should not be added and
      rounding is highly discouraged.

