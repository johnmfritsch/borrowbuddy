
# Purpose: "What changed for users" (concise, feature-focused)

## [2026-10-21] - Gunicorn Server, Health Check and Safer Deploys

### Changed
- **Runs on Gunicorn instead of Flask's built-in server**: one shared launcher (`scripts/start_borrowbuddy.py {dev|prod}`) starts both environments, waits for the HTTPS certificate, and writes a PID file. Stop and restart scripts now stop the server by that PID and confirm it is serving before reporting success.
- **Deploy is safer**: `deploy_to_prod.sh` checks the Python runtime first, compares the dev migrations (not prod's) against the prod database, backs up uncompressed, and treats a server that does not come back healthy as a failed deploy.

### Added
- **`/health` endpoint**: a no-login check used by the restart scripts and the shared NAS watchdog.

### Fixed
- **Production server failed to start after deploy**: The inline `python3 -c` command used by the restart script was unreliable under memory pressure (BusyBox nohup + large inline command). Replaced with a proper `start_prod.py` launcher script matching the existing `start_dev.py` pattern.
- **Restart script now uses `start_prod.py`**: Cleaner process management with `pkill -f 'start_prod.py'` and a curl health check to verify the server is responding after restart.
- **Cleaned up orphaned debug scripts**: Removed leftover debugging artifacts from production (`check_port.py`, `launch_prod.py`, `restart_prod2.py`, etc.).

## [2026-02-18] - Fix Edit Item Page Slow Image Loading

### Fixed
- **Edit item gallery now uses thumbnails**: The photo gallery on the edit item page was loading full-resolution original images (~2-5 MB each) at 120×120px display size. Now uses `photo_uri_thumb` (~5-10 KB) when available, with fallback to original. Dramatically faster on mobile/Android.
- **API returns thumbnail URIs**: `GET /api/items/<id>/photos` now includes `photo_uri_thumb` and `photo_uri_display` fields so clients can choose appropriate size.
- **Edit form photo upload generates variants**: Photos uploaded via the edit item form (legacy path) now call `generate_image_variants()` and store `photo_uri_thumb`/`photo_uri_display` in `item_photos`, consistent with the API upload path.

## [2026-02-11] - Image Variant Bugfixes (Critical Performance Fix)

### Fixed
- **Image variants not loading (CRITICAL)**: All 6 bugs preventing the image variant system from working have been fixed
  - `sync_default_photo()` now syncs `photo_uri_thumb` and `photo_uri_display` to items table (was only syncing `photo_uri`)
  - Items list query now includes thumb/display columns so templates can use them
  - Current Loans (where) query now includes thumb/display columns
  - API items endpoint now includes thumb URI for loan page item picker
  - Loan route photo uploads now generate image variants (was inserting without variants)
  - Fixed wrong URL prefix (`/BorrowBuddy/` instead of `/BorrowBuddy_dev/`) in dev database
- **Production variant files regenerated**: All 43 photos in production now have thumbnail and display variants on disk (previously had 0)
- **Database fully synced**: Both `item_photos` and `items` tables now have correct thumb/display URIs in both dev and prod

### Technical
- Root cause: The image variant system was implemented but never connected end-to-end. Variants were generated on disk (dev only) and stored in `item_photos`, but the `items` table cache was never populated, and SQL queries never selected the variant columns. Templates fell back to loading full-resolution originals (2-47 MB each).
- Impact: Items list was loading ~292 MB of original images instead of ~140 KB of thumbnails (2000x difference)


## [2026-02-11] - Image Performance Optimization Complete

### Added
- **Image Variant Generation**: Automatic creation of optimized image variants on upload
  - 150px thumbnail variant (`photo_uri_thumb`) for list/card views
  - 600px display variant (`photo_uri_display`) for detail/gallery views
  - Original full-resolution image (`photo_uri`) preserved for lightbox viewing
  - Quality levels: 75% for thumbnails, 85% for display, 95% for originals
- **Lazy Loading**: All images in list views now use HTML5 `loading="lazy"` attribute
  - Prevents below-fold images from loading until user scrolls
  - Significant performance improvement on mobile with long lists
- **HTTP Cache Headers**: Added cache control middleware for optimal browser caching
  - Static images: 1-year cache with ETag validation
  - API responses: 5-minute cache for freshness
  - Eliminates re-downloading unchanged images on repeat visits
- **Backfill**: All 33 existing photos automatically processed to generate variants

### Fixed
- **Image Load Performance**: 80-98% reduction in bytes transferred for image-heavy pages
  - Items list: 34MB → 35KB per page (980x reduction)
  - Loan history: Similar dramatic improvements
  - Mobile performance: Dramatic improvement on cellular/WiFi
- **Dev Server Python Interpreter Issue**: Resolved recurring startup failures
  - Root cause: Pillow dependency installed in wrong Python interpreter
  - Now correctly using `/volume1/.@plugins/AppCentral/python3/bin/python3`
  - Documented fix in MEMORY.md to prevent future occurrences

### Technical
- **New Database Columns**: `photo_uri_thumb`, `photo_uri_display` added to `item_photos` and `items` tables
- **New Utility Function**: `generate_image_variants()` in utils.py uses Pillow for image processing
- **Updated Upload Routes**: All image upload endpoints now generate and store variants
- **Updated Templates**: items.html, where.html, loan.html, edit_item.html, edit_loan.html, duplicate-checker.js
- **Dependencies**: Added Pillow==10.1.0 for image processing

## [2026-02-07] - Multiple Photos Per Item UI (Part B2 Complete)

### Added
- **Loan Page (Existing Items)**: Photo Picker Modal for managing multiple photos
  - Click photo button to open modal showing all item photos
  - Set default photo (star icon), delete photos (X icon)
  - Upload new photos via "Take Photo" or "Choose from Gallery" buttons
  - Photo button shows count: "Photos (3)" for multiple, "Change Photo" for single
- **Loan Page (New Items)**: Multi-photo upload support
  - Two separate buttons: "Take Photo" (camera) and "Choose from Gallery" (multi-select)
  - Preview thumbnails with remove button before submitting
  - First photo automatically becomes default
- **Edit Loan Page**: Read-only photo gallery showing all item photos (80x80 thumbnails, yellow border on default)
- **Mobile/Desktop Detection**:
  - Desktop: "Choose from Gallery" renamed to "Upload Photo" for clarity
  - Mobile: Autofocus removed from search fields to prevent keyboard popup
  - Global `window.isMobile` flag available on all pages

### Fixed
- **Multi-photo upload bug**: Loan page only saved first photo when multiple selected - now correctly saves all photos via `request.files.getlist('photo')`
- **JavaScript errors**: Removed element references (photo_preview, remove_photo) now properly guarded against null
- **Layout bug**: Extra closing `</div>` in loan form breaking container width - removed

### Technical
- loan.html: Photo Picker Modal with gallery rendering and AJAX operations
- app.py: loan() POST now handles multiple file uploads for new items
- base.html: Mobile detection script using userAgent + maxTouchPoints
- All photo operations use existing `/api/items/<id>/photos` endpoints

## [2026-02-07] - UI Text Update

### Changed
- Updated "Items Loaned" page heading to "Current Loans" for improved clarity

---

## [2026-02-07] - Multiple Photos Per Item (Backend)

### Added
- New `item_photos` database table to support multiple photos per item
- Migration 008: Creates item_photos table and migrates existing photo data
- New API endpoints: GET/POST/DELETE for item photos, set_default endpoint
- `sync_default_photo()` helper keeps items.photo_uri in sync with item_photos default
- Dual-write: all photo operations now write to both items.photo_uri and item_photos
- `photo_count` field added to items API response

### Technical
- items.photo_uri kept as denormalized cache of default photo for backward compatibility
- All existing UX unchanged - backend-only preparation for multi-photo UI

---


## [2026-02-07] - Duplicate Detection Refactoring and UI Improvements

### Added
- Return notes now automatically append to item description with format: "Return note from: MM/DD/YYYY - [note]"
- Return notes continue to be saved on loan record for history tracking

## [2026-02-07] - Improved Archived Item Detection

### Changed
- Updated duplicate item detection dialog to clearly indicate when an item is "Archived" rather than "removed"
- Changed "Edit Existing" button to "Reactivate" (green button) when encountering archived items
- Improved messaging: "An item named [name] was found but is Archived"

### Added
- New `/api/items/reactivate` endpoint to reactivate soft-deleted items
- Reactivation functionality now available from both Add Item page and Loan page quick-add

---



### Added
- Shared duplicate detection infrastructure:
  - `/static/js/duplicate-checker.js` - Reusable DuplicateChecker class for all duplicate detection
  - `/templates/macros/duplicate_modals.html` - Reusable Jinja macros for duplicate detection modals
- Duplicate detection now works on loan page for both contacts and items
- Auto-select edited contact on loan page after using "Edit Existing" from duplicate modal
- Session storage used to preserve contact selection across edit flow

### Changed
- **Refactored duplicate detection code** - Eliminated ~200+ lines of duplicate code across add_contact.html, add_item.html, and loan.html by creating shared JavaScript module and Jinja macros
- Contact and item names now automatically capitalized using `.title()` when created via loan page (consistent with add_contact and add_item pages)
- Loan page UI improvements:
  - "Choose Different Item" and photo buttons moved inside item card and styled as links (matching contact section)
  - "Return Date (Optional)" and "Notes (Optional)" labels now show "(optional)" in smaller, lighter font
- Modal dismiss handling improved to not interfere with Bootstrap's native functionality

### Fixed
- **Fixed** "Add as Duplicate" button not working - Event listeners were being destroyed by button cloning code
- **Fixed** Contacts created via loan page not appearing in Manage Contacts - `is_active` column wasn't being set to 1
- **Fixed** Case-sensitivity issue - Contact/item names entered in lowercase now properly capitalized for consistent alphabetical sorting
- **Fixed** Copy-paste bugs in edit_contact and edit_item routes (were checking wrong tables)
- **Fixed** Modal event listeners attaching multiple times causing duplicate handling
- **Fixed** "Edit Existing" redirect not working from loan page - Added `?next=loan` parameter support

### Documentation
- Added `/REFACTORING_PLAN.md` - Detailed plan for duplicate detection refactoring
- Added `/REFACTOR_USAGE.md` - Usage guide for implementing duplicate detection in new pages

## [2026-02-05] - Fix item deletion and session persistence

- **Fixed** item delete route crashing due to missing `from pathlib import Path` import — soft-delete and audit logs were never executing
## [2026-02-06] - Search Functionality for Items Loaned Page

### Added
- Search bar on Items Loaned (where.html) page with real-time filtering
- Searches across: item name, contact name (borrowed by), loan date, return date, and notes
- Case-insensitive client-side filtering matching the pattern used on contacts and items pages


- **Fixed** `SECRET_KEY` regenerating randomly on every app restart, which invalidated all session cookies — key is now generated once and persisted to `secret_key.txt`
- **Fixed** delete confirmation JS blindly showing "Item deleted" regardless of server response — now checks response status and alerts on failure
- **Fixed** Python 2 `print >>` syntax in `log_audit` error handler — errors were silently swallowed in Python 3
- **Fixed** deploy script to exclude `secret_key.txt` from rsync so prod sessions survive deployment


## [2026-02-03] - UI Improvements: Page Titles, Action Toolbar, New Loan Button

### Added
- "New Loan" button on Items Loaned page (same style/position as Add Contact / Add Item buttons)
- Consistent page titles on all sub-pages: arrow + centered bold title row using {% block page_title %}
  - Applied to: Manage Contacts, Manage Items, Items Loaned, Loan Something, Add/Edit Contact, Add/Edit Item, Edit Loan

### Changed
- Page titles moved from inside content area to a flex row next to the back arrow (base.html page_title block)
- "Items Currently Loaned Out" heading renamed to "Items Loaned"
- Back arrow margin removed; arrow and title now share a flex row with consistent spacing

### Fixed
- Delete modal cancel no longer leaves items visually selected; selection clears on modal dismiss (contacts, items, and where pages)
- Complete modal cancel on Items Loaned page now also clears selection on dismiss

## [2026-02-03] - Hamburger Drawer Menu

### Added
- Hamburger menu button in navbar (left of home icon) that opens a slide-from-left drawer
- Drawer menu with items: My Profile, Settings, Invite Friends, BorrowBuddy Features, and Logout
- Dark overlay behind drawer; closes on overlay click, X button, or Escape key
- Four stub "Coming Soon" pages: /my-profile, /settings, /invite-friends, /borrowbuddy-features

### Changed
- Removed email display and inline Logout button from navbar; Logout moved into drawer menu


## [2026-02-03] - Contact Duplicate Detection and Multi-Value Import Fixes

### Added
- `/api/contacts/reactivate` endpoint to restore soft-deleted contacts (sets is_active = 1 with audit logging)
- Multi-value picker modal on both Loan and Add Contact pages: when importing a phone contact with multiple emails or phone numbers, user is prompted to choose which one to store
- Duplicate contact modal on Loan page now differentiates active contacts ("Contact Already Exists") from soft-deleted contacts ("Previous Contact Found") with appropriate Re-add action

### Fixed
- Loan page duplicate modal: Bootstrap Modal instance created fresh on each show() call, causing silent failures on mobile; switched to single initialized instance (same pattern as Add Contact page)
- Loan page duplicate modal: "Use This Contact" / "Re-add This Contact" button handler was calling bootstrap.Modal.getInstance() which returned null; now references the initialized instance directly
- Loan page form submission blocked by required attribute on contact_name after switching from New Contact to Existing Contact via duplicate detection; dupModalUseExisting handler now clears required flag
- Add Contact page duplicate modal: dupModalMessage.innerHTML was destroying nested duplicate_name element, causing null reference crash; removed orphaned getElementById line
- Add Contact page: broken Jinja tag `{ config.URL_PREFIX }` (single braces) in edit_existing_btn href fixed to `{{ config.URL_PREFIX }}`
- Duplicate check API: added is_active to SELECT columns in both exact and fuzzy match queries so frontend can distinguish active vs soft-deleted contacts


## [2026-02-02] - Audit Log System

### Added
- Audit log system for tracking all user activity
- audit_log database table with columns: id, user_id, user_email, action, entity_type, entity_id, entity_name, details, ip_address, timestamp
- Database indexes on user_id, timestamp, action, entity_type for performance
- log_audit() function that reuses existing database connections for efficiency
- Migration 006: 006_add_audit_log.py
- Audit logging for all CRUD operations:
  - Login/logout events
  - Loan creation and completion
  - Item create/update/delete operations
  - Contact create/update/delete operations
- Admin panel audit log viewer with:
  - Filterable table by user, action, entity type, date range
  - Color-coded action badges
  - Real-time display of user activity
  - Manual log cleanup functionality
- Three API endpoints for audit log management:
  - GET /api/admin/audit_log - View logs with filters
  - GET /api/admin/audit_log/stats - Get filter statistics
  - POST /api/admin/audit_log/clear - Manual log cleanup

### Changed
- Photo upload label formatting: Add Photo button with Optional text
- Removed filename display after photo selection for cleaner UI
- Fixed config passing to items.html template for proper URL generation

### Fixed
- Audit logging performance issue - now reuses existing DB connections instead of opening new ones
- Missing db.commit() in loan creation route
- Item deletion now properly redirects instead of showing not found error
# BorrowBuddy Changelog

All notable changes to this project will be documented in this file.

## [2026-02-02] - Admin Functionality

### Added
- Admin functionality restricted to admin@example.com
- `is_admin` column added to users table (INTEGER DEFAULT 0)
- Database index on `is_admin` column for performance
- `admin_required` decorator for protecting admin-only routes
- Admin panel route at `/admin`
- Admin button on home page (fourth row, yellow/warning styled)
- Admin panel template with placeholder sections for:
  - User Management
  - System Statistics
  - Database Maintenance
  - Audit Logs
  - System Settings
- Migration script: `migrate_admin.py`

### Changed
- None

### Security
- Admin button only visible to users with `is_admin = 1`
- Admin routes protected by `@admin_required` decorator
- Non-admin users attempting to access `/admin` receive 403 Forbidden response
- Defense in depth: visibility control (template) + access control (decorator)

## [2026-02-01] - Items and Contacts Management

### Added
- Manage Items page with list view, search, edit, and delete functionality
- Manage Contacts page with list view, search, edit, and delete functionality
- Contact duplicate detection with fuzzy matching and merge capability
- Item duplicate detection with fuzzy matching and merge capability
- Import from phone contacts feature (mobile only)
- Phone number normalization to E.164 format for SMS compatibility
- Auto-capitalization: items use capitalize(), contacts use title()
- Status badges showing active loans/borrows on contacts page
- Section headers on loan page: What are you loaning? and Who are you loaning it to?
- Soft delete for items and contacts (is_active flag) to preserve historical data

### Changed
- Loan page now defaults to Existing Item mode (was New Item)
- Items list on loan page now sorted alphabetically by name
- Delete functionality changed from hard delete to soft delete for history preservation
- Special characters in names now properly escaped using Jinja tojson filter

### Fixed
- Inactive items no longer appear on loan screen (added is_active filter to api_items)
- JavaScript syntax errors when deleting items with apostrophes or special characters
- Delete button now uses data attributes instead of inline onclick to avoid escaping issues
- NULL active_loans values now properly default to 0 to prevent JavaScript errors
