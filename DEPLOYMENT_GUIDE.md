# BorrowBuddy Production Deployment Guide

## Pre-Deployment Summary

### New Features Being Deployed
1. **Return Item Augmentation**
   - Add return notes when completing a loan
   - Optional return photo capture
   - Checkbox to update item's primary photo with return photo
   - 4 return dispositions: Returned Normally, Returned Damaged, Lost/Not Returned, Cancelled

2. **Loan Page Improvements**
   - Contact section: Existing Contact is now default and visible on load
   - Item selection: Active loans are filtered out (can't loan same item twice)
   - Soft-deleted items are hidden from selection
   - Form resets after creating a loan
   - Custom "📷 Add Photo" buttons on all file inputs
   - Item name field appears before photo upload for new items
   - Selected item shows compact view with dynamic Add/Change Photo button

3. **Bug Fixes**
   - Fixed photo URI paths for dev environment
   - Fixed deleted contacts appearing on loan page
   - Fixed items display showing proper "No photo" placeholder

### Database Changes
- **New column:** `loans.return_photo_uri` (TEXT, nullable, indexed)
- **Requires migration:** Yes, after code deployment

### Files Modified
- `app.py` - Backend logic for return augmentation, API filters
- `templates/loan.html` - Enhanced item selection and contact display
- `templates/where.html` - Return modal with notes and photo
- `templates/items.html` - "No photo" placeholder
- `templates/add_item.html` - Custom photo button
- `templates/edit_item.html` - Custom photo button

---

## Pre-Deployment Checklist

Run the verification script first:
```bash
ssh <user>@192.168.x.x
cd /volume1/Web/BorrowBuddy_dev
python3 pre_deployment_check.py
```

Ensure all checks pass before proceeding.

---

## Deployment Steps

### Step 1: Backup Current Production
```bash
ssh <user>@192.168.x.x
cd /volume1/Web/BorrowBuddy_dev
./deploy_to_prod_TEMPLATE.sh
```

**What this does:**
- Stops production server (port 7781)
- Creates timestamped backup in `/volume1/Web/BorrowBuddy_backups/`
- Copies all code from dev to production (excluding database)
- Restarts production server

**Expected output:**
```
=========================================
Deploy BorrowBuddy Dev to Production
=========================================

WARNING: This will:
  1. Stop production server
  2. Backup current production to /volume1/Web/BorrowBuddy_backups
  3. Copy development code to production
  4. Keep production database (NOT overwritten)
  5. Restart production server

Do you want to continue? (yes/no): yes

Stopping production server...
Creating backup: borrowbuddy_prod_YYYYMMDD_HHMMSS.tar.gz
Backup created successfully

Copying development code to production...
Restarting production server...

=========================================
Deployment complete!
=========================================

Production server: https://192.168.x.x:7781/BorrowBuddy/
```

### Step 2: Run Database Migration
```bash
cd /volume1/Web/BorrowBuddy
python3 migrate_return_augmentation_prod.py
```

**Expected output:**
```
=== Production Database Migration ===

Adding return_photo_uri column to loans table...
✓ Column added successfully
Creating index on return_photo_uri column...
✓ Index created successfully

=== Verifying migration ===
Loans table columns:
  - id: INTEGER
  - item_id: INTEGER
  - contact_id: INTEGER
  - return_date: TEXT
  - disposition: INTEGER
  - date_loaned: TEXT
  - notes: TEXT
  - user_id: INTEGER
✓ - return_photo_uri: TEXT

✓ Migration completed successfully!
```

### Step 3: Verify Production
Open browser and test:
- **URL:** https://192.168.x.x:7781/BorrowBuddy/

**Test checklist:**
- [ ] Login works
- [ ] Dashboard loads with current loans
- [ ] "Loan Something" page loads
- [ ] Only available items show (no active loans, no deleted items)
- [ ] Contact selection works (Existing Contact is default)
- [ ] Can create a new loan
- [ ] "Where's My Stuff?" page shows active loans
- [ ] Click "Delete" on a loan, modal opens with return options
- [ ] Can add return notes
- [ ] Can capture/upload return photo
- [ ] Checkbox for "Make this the new photo for the item" works
- [ ] Can complete loan with all 4 disposition options
- [ ] Manage Items page shows items correctly

---

## Rollback Procedure

If issues are found after deployment:

```bash
ssh <user>@192.168.x.x
cd /volume1/Web/BorrowBuddy_backups

# List backups to find the correct one
ls -lh borrowbuddy_prod_*.tar.gz

# Extract the backup (replace TIMESTAMP with actual value)
cd /volume1/Web
tar -xzf BorrowBuddy_backups/borrowbuddy_prod_TIMESTAMP.tar.gz

# Restart production
cd /volume1/Web/BorrowBuddy
./restart_borrowbuddy.sh
```

**Note:** Rollback will NOT undo the database migration. The `return_photo_uri` column will remain (harmless, just unused).

---

## Post-Deployment Notes

### Database Migration is One-Way
The migration adds a column but there's no automatic rollback. If you need to remove the column:
```bash
# NOT RECOMMENDED - only if absolutely necessary
# Would require creating new table without the column and copying data
```

### Photo Storage
Return photos are stored in `/volume1/Web/BorrowBuddy/static/images/` with prefix `RETURN_YYYYMMDD_HHMMSS_filename.jpg`

### Known Limitations
- Return photos are optional
- No viewing of historical return photos (future enhancement)
- No notification to borrower when item marked as damaged

---

## Support

If deployment issues occur:
1. Check server logs: `tail -f /volume1/Web/BorrowBuddy/borrowbuddy.log` (if exists)
2. Check if server is running: `ps aux | grep python3 | grep 7781`
3. Manually restart: `cd /volume1/Web/BorrowBuddy && ./restart_borrowbuddy.sh`
4. Rollback using procedure above

---

## Summary

**All checks passed ✓**

You are ready to deploy to production. The deployment process:
1. Takes automatic backup
2. Copies code (preserves production database)
3. Requires manual migration script run
4. Can be rolled back if needed

**Estimated downtime:** 1-2 minutes during deployment

**Risk level:** Low (backup taken, database preserved, rollback available)
