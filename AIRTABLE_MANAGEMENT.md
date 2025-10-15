# Airtable Data Management Scripts

## 🗑️ Clear Airtable Data Script

### Purpose
Safely deletes **all records** from your Airtable VA tables while **preserving the schema** (field structure). This is useful for:
- Resetting the database between campaigns
- Cleaning up test data
- Starting fresh with new assignments

### Prerequisites
- Python 3.7+
- `pyairtable` package installed (`pip install pyairtable`)
- `python-dotenv` package installed (`pip install python-dotenv`)
- Valid Airtable credentials in `.env` file

### Environment Variables Required
Your `.env` file must contain:
```bash
AIRTABLE_ACCESS_TOKEN=your_token_here
AIRTABLE_BASE_ID=your_base_id_here
NUM_VA_TABLES=80  # Number of VA tables to clear
```

### Usage

#### Basic Usage
```bash
cd server
python3 clear_airtable_data.py
```

#### What Happens
1. **Loads configuration** from your `.env` file
2. **Displays summary** of what will be deleted
3. **Asks for confirmation** before proceeding
4. **Clears all tables** in batches (respects Airtable API limits)
5. **Shows detailed progress** for each table
6. **Displays summary** of deleted records

### Example Output
```
🗑️  Airtable Data Cleaner
==================================================

📋 Configuration:
   Base ID: appSiGZgBbPvLiTfq
   Number of tables: 80
   Tables: Daily_Outreach_Table_01 to Daily_Outreach_Table_80

⚠️  WARNING:
   This will permanently delete ALL records from 80 tables.
   The table structure (fields) will be preserved.

Proceed? (y/n): y

✓ Connected to Airtable

Starting cleanup...

[1/80] Clearing Daily_Outreach_Table_01... ✓ done (180 records deleted)
[2/80] Clearing Daily_Outreach_Table_02... ✓ done (180 records deleted)
[3/80] Clearing Daily_Outreach_Table_03... ✓ done (180 records deleted)
...

==================================================
📊 Summary:
   ✓ Successfully cleared: 80/80 tables
   📝 Total records deleted: 14,400

✅ All tables cleared successfully!
```

### Safety Features
- ✅ **Confirmation required** - Won't delete anything without explicit 'y' confirmation
- ✅ **Batch processing** - Respects Airtable API limits (10 records per batch)
- ✅ **Rate limiting** - Prevents API throttling (5 requests/second max)
- ✅ **Error handling** - Gracefully handles network or permission errors
- ✅ **Schema preservation** - Only deletes records, keeps all fields intact
- ✅ **Progress tracking** - Shows detailed status for each table

### Troubleshooting

#### Error: AIRTABLE_ACCESS_TOKEN not found
Make sure your `.env` file exists in the `server/` directory and contains the token.

#### Error: Table not found
Verify that:
1. Your `NUM_VA_TABLES` matches the actual number of tables in Airtable
2. Tables are named exactly: `Daily_Outreach_Table_01`, `Daily_Outreach_Table_02`, etc.

#### Error: Permission denied
Ensure your Airtable token has `data.records:write` and `data.records:read` permissions.

### Alternative: Manual Cleanup
If you prefer to clear specific tables only, you can modify the script or use the Airtable web interface.

---

## ⚠️ Important Notes

1. **This action is irreversible** - Deleted records cannot be recovered
2. **Always backup important data** before running cleanup scripts
3. **Test in development first** if you have a separate Airtable base for testing
4. The script respects Airtable API limits but may take 1-2 minutes for 80 tables

---

## Support
For issues or questions, check the main project README or contact the development team.
