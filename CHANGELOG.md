## [Unreleased]

### Added

### Changed

### Deprecated

### Removed

### Fixed

### Security

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
