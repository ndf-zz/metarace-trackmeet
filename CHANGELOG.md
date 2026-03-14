## [Unreleased]

### Added

### Changed

### Deprecated

### Removed

### Fixed

### Security

## [1.13.8]

### Added

   - Add standards module for category info
   - Include density estimate with weather readings
   - Add penalty objects to data bridge
   - Add session dialog
   - Add break dialog
   - Add competition builder scripts for standard meets
   - Include report print options from roadmeet
   - Dump per-rider detail reports on export from ittt and f200
   - Restore walk over function to ittt for final rounds
   - Others places for collecting and optionally ranking non-qualified
     competitors in classification
   - Add meet contact email for issues/feedback link on result pages
   - Add config schema for classification handler
   - Add manual override of final ranking in classification
   - Add option to force single page meet index on result
   - Transfer team members from qual to final on team sprint/team pursuit
   - Autostart riders recognises special flag 'Q' to indicate all
     qualified riders from nominated event
   - Lookup weather adjustments for printed timing detail report
   - Add Ctrl-A shortcut to add starters to current event

### Changed

   - Top-N can specify negative qualifiers for eliminating n competitors
     that started from bunch events
   - Reorder weather presentation to match AC weather site
   - Simplify start and result line packing on bridge
   - Automatically fill qualtime/rank from qualification objects
   - When adding new event and if evid clashes, change only the edited event
   - Meet date is specified by start and end date objects
   - Automatically adjust session ids on events when reordered
   - Discard precision on compute of net times, then report diffs from taken
     net times.
   - On event delete, move to config file to backup
   - Append 'Heat 1' to sprint final listing on event index
   - Autoplace lookup for ps and classification others allows n- notation
   - Rename classification class Classification
   - Generate section subheadings in event library, across all handler types
   - Assume starttime = 0 when finish set but start time omitted
   - Allow direct edit of elapsed time in flying 200

### Deprecated

   - Text-only announcer output deprected, to be replaced with data bridge
     and web console

### Removed

   - Remove user-supplied free-form date string from meet properties

### Fixed

   - Use reference no of sprint handler when indexing sprint heat pseudo event
   - Add category entry to riderdb when adding event
   - Change event class name to Event to avoid namespace clash
   - Improve competition and phase labels on bridge objects
   - Correct others sorting in sprint round when using qualification time
   - Truncate points race intermediate header on small scoreboard
   - Don't add placeholder competitors to riderdb
   - Apply qualified badge to A/B in current object at finish
   - Repair handling of placeholders, missing places and tied rankings
     in classification
   - Correct placing of riders in flying 200 when no time recorded
   - Allow manual ittt operation when distance not set
   - Correct window title for del starters popup
   - Retain start time for manually adjusted flying 200 and ittt

### Security

## [1.13.7] 2026-01-29

### Added

   - Configure Heat 2 and Heat 3 event nos within sprint round handler
   - Add pseudo event handler for sprint 2/3
   - Mark heat label on sprint final scoreboard info page
   - Include link to next event fragment in bridge current object
   - Provide scoreboard type hint in bridge current object
   - Re-run export on completion if any export requests blocked while in progress
   - Hour record event handler

### Changed

   - Advance event when sprint running will select next contest if possible
   - Advance to break event when type is sprint heat will open parent sprint handler
   - Mark preferred page breaks on session boundaries in program index
   - Allow addition of custom number series by category lookup to program rider list

### Fixed

   - populate contest result when known for sprint finals
   - suppress "win" badges on byes
   - don't re-order points race rider model on save
   - don't update eventdb prefix/info on event load
   - add workaround for reordering of starters on save in flying 200 and ittt

## [1.13.6] - 2025-12-31

### Added

   - include optional introduction sections to printed program
   - add prefix to data bridge telegraph topics
   - add dnf, abd, dns, dsq handling on points and race handler
   - add pursuit dual lane autotime
   - number collection report
   - pull handicap mark from seeding if set (pre 1.12 behavour)
   - fetch normalised event number from eventdb
   - provide '-' shortcut in points places to place all in riders 1st
   - allow configuration of aggregate type labels, and current meet label

### Changed

   - convert stat button to use symbolic svg icon
   - handle scratch race as points race with single sprint
   - rename lap-based scoring type in points race from madison to laps
   - suppress sub-fragments and intermediates in points handler when
     type is scratch
   - update race handler to use "In" and dnf codes instead of "DNF"
   - start macro button also forces event finish and updates current
   - suppress draw no on keirin/sprint result reports
   - re-order riders in generic race after assigning places
   - suppress heat numbers on sprint final anchor
   - allow repeated/duplicate badges on data bridge rider records
   - classification imports depends and autospec from event listing to
     showevents and placesrc
   - use data bridge keys to look up omnium components instead of prefix
     and info
   - omnium startlist mid-event includes standings
   - automatically add blank cat riders to bridge categories
     as workaround for carnival type meets
   - allow ps info col to override rider class label
   - databridge event numbers map to list of events instead of single
     value

### Removed

   - remove cmp() based sorters from points and race handler

### Fixed

   - uppercase rider series ID for rider listing
   - fix broken data bridge session start time
   - fix madison team listing on result report
   - fix rider no reporting on team members in result report
   - update and correct laps-down reporting in points race when scoring
     type is laps-based.
   - fix sorting of others by qualifying time in result gen
   - don't issue a downtime to a dns, dnf, abd or dsq rider (f200/ittt)
   - restore broken mid competition omnium seedings
   - normalise event number presentation across reports scb and data bridge
   - fix aggregate points extension

## [1.13.5] - 2025-12-05

### Added

   - log current weather on chronometer trace at start of heat
   - detail report section on time trial/pursuit events
   - autotime functionality for ittt handler
   - add databridge schema reference document
   - add databridge feilds to event listing
   - select scoreboard image overlay from SCB menu/hotkey
   - add dependency 'all' to always recompute on export
   - add key 'eventStart' to current to mark rough start of event,
     separate to rolling clock start
   - save current time of day to event db when event is started or presented
   - force reload of competitors in sprnd with Ctrl+F3
   - add lapscore interface to track laps to go via databridge

### Changed

   - write competitor Class Label to info column instead of ucicode
   - default autotime to True for pursuit/tt events
   - log interval/split to chronometer trace instead of split/lap
   - replace Comet with Weather object
   - re-order event context with add/remove starters first
   - alter event columns to remove clashes with data bridge fragments
     meet/category/competition/phase/contest/heat
   - fill page body of scoreboard test screen with random chars instead
     of repeated pattern
   - send general clearing before meet/event info scoreboard is drawn
   - mark all result events dirty when compiling final result
   - format event db data types integer, boolean and datetime

### Removed

   - remove intermediate sprint/split timer from points race handler
   - remove current overlay tracking from sender object
   - remove set overlay calls from scbwin, allow postxt to select
     text matrix automatically
   - remove showcats option in favour of class labels

### Fixed

   - fix typo strops.posint in infoline method
   - fix type sartswith in ps and teamagg
   - load points map in team agg only once for each event
   - Ctrl+F3 in keirin sets random draw but does not trigger startlist
   - Order madison pairs Black/Red in ps handler

## [1.13.4] - 2025-09-16

### Added

   - Team members saved with event handler for ittt events
   - Include team names on scb when space permits
   - Add comet configuration to meet properties dialog
   - quit with error if loadconfig detects roadmeet configuration
   - Return Daktronics/Venus output option to txt scb sender (DGV)
   - Team / individual points aggregate handler (Blackline)

### Changed

   - Adjust vertical spacing on scb for rows > 7
   - set program and application names to match .desktop file
   - set default logo by xdg name instead of file
   - use __version__ instead of VERSION
   - Suppress event id/no when not numeric
   - Uppercase scoreboard content for Dak sender when line > 1
   - Format None, bool and int values in eventdb save

### Deprecated

   - Use of 'tandem' category for PARA 'B' sport class riders

### Fixed

   - Add missing abd callback in flying 200 handler
   - Mark and remember assigned bye ranking in sprnd
   - Standardise report headings and scoreboard info lines
   - Mark ps finalised only after all intermediates have result

## [1.13.3] - 2025-07-04

### Added

   - Added topn field for marking qualified riders
   - Recover start impulse enabled for all timed events
   - Add upgrade function to about dialog
   - Reorder schedule of events by drag and drop
   - Event number override added to all views
   - Add function to clear/reset a closed event
   - Delete rider from meet
   - Duplicate event entries
   - Track timer precision set in timerpane
   - Add/remove starters from event context menu

### Changed

   - Rider db column names and default order updated
   - Add riders from event db no longer supported
   - Autospec no longer property of event handler, read
     instead from eventdb
   - Allow edit of points race intermediates after race start
   - All handlers can now load and save without UI
   - Add new event opens event edit dialog instead of handler properties
   - Display timer log messages on status line
   - Increase default window size to 1200x680
   - Showinfo defaults to false on new events
   - Simplify riders pane view and display duplicated in italics
   - Standardise event and rider labels and prompts
   - Name presentation and editing standardised across all handlers
   - Use 5 chars for width of all info/nation columns on text scb
   - Allow withdrawl/return of riders in non-elimination race handler
   - Add property dialog for sprint round/final
   - Track timer teams flag get by series or evtype

### Deprecated

   - Event distance/laps in handler properties - use event db laps instead
   - Event series in handler properties - use event db instead

### Removed

   - Add riders from eventdb no longer supported - use event context
   - Superfluous JSON exports removed from export and index
   - Startplace offset removed from race handler
   - Remove superfluous destroy methods in event handlers

### Fixed

   - Fixed GTK segfault from export thread
   - Event and rider change notifications connected to all event handlers
   - Competitor 'club' field fixed in points race startlist
   - Close a deleted event handler if currently open
   - Event ID change
   - Don't save open event twice if meet window closed
   - Ensure BIB.series capitalisation in all handlers
   - Don't announce withdrawn/eliminated riders if placed

### Security

   - Remove development venv from built package

## [1.13.2] - 2025-06-14

### Added

   - Command line option --create to create and load empty meet
   - Pre-load common omnium options and populate references automatically
   - A5 booklet template for program export
   - Add standard sponsor and prizemoney footers on program reports
   - Include optional list of competitors at start of program
   - Include canonical reference on reports for auto reloader

### Changed

   - Launch without meet path opens a path chooser dialog
   - Edit dialog height constrained to monitor size
   - Spreadsheet outputs use xlsx format
   - Eventdb moved into trackmeet package
   - Points race allows fractional lap intermediates
   - Suppress team members in program exports
   - List configured competitions separately in index of events
   - Do not display timer impulses on status bar or log view

### Deprecated

   - Add riders from eventdb to be removed
   - Distance configuration in event handler properties
   - Series edit in event handler properties

### Fixed

   - Repair contest label and intermediate counts in points race
   - Remove silent truncation of prefix and info within event handler UI
