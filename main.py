#!/usr/bin/env python
# coding: utf-8

# In[1]:


import sqlite3
from typing import Tuple, Optional, Dict, List

# ================================================
# BLOCK 1: CONSTANTS — No magic strings anywhere
# ================================================
DEPT_IT      = "IT Support"
DEPT_BILLING = "Billing"
DEPT_HR      = "HR"
DEPT_GENERAL = "General"

# ================================================
# BLOCK 2: STATE MACHINE
# Defined at module level — created ONCE in memory,
# not rebuilt on every function call.
# ================================================
VALID_TRANSITIONS: Dict[str, List[str]] = {
    'Open':        ['In Progress', 'Resolved'],  # Direct resolve allowed
    'In Progress': ['Resolved'],
    'Resolved':    []                             # Terminal — no way back
}

# ================================================
# BLOCK 3: CONNECTION FACTORY
# PRAGMA foreign_keys resets on every new connection.
# This factory guarantees FK enforcement is ALWAYS active.
# ================================================
def get_connection() -> sqlite3.Connection:
    """Creates a DB connection with foreign key constraints enforced."""
    conn = sqlite3.connect('smart_helpdesk.db')
    conn.execute('PRAGMA foreign_keys = ON;')
    return conn

# ================================================
# BLOCK 4: DATABASE INITIALIZATION — 3-table schema
# ================================================
def initialize_database(conn: sqlite3.Connection) -> None:
    """
    TABLE 1 — departments: PARENT (Primary Key: dept_id)
    TABLE 2 — tickets: CHILD (Foreign Key: dept_id → departments)
    TABLE 3 — ticket_logs: AUDIT TRAIL (Foreign Key: ticket_id → tickets)
    INDICES  — B-tree on status and priority = O(log n) lookups
    """
    try:
        cursor = conn.cursor()

        # TABLE 1: Parent — all departments live here
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS departments (
                dept_id   INTEGER PRIMARY KEY AUTOINCREMENT,
                dept_name TEXT    UNIQUE NOT NULL
            )
        ''')

        # TABLE 2: Child — each ticket belongs to one department
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tickets (
                ticket_id   INTEGER PRIMARY KEY AUTOINCREMENT,
                title       TEXT    NOT NULL,
                description TEXT    NOT NULL,
                category    TEXT    NOT NULL,
                priority    TEXT    NOT NULL,
                status      TEXT    NOT NULL DEFAULT 'Open',
                dept_id     INTEGER NOT NULL,
                created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (dept_id) REFERENCES departments(dept_id)
            )
        ''')

        # TABLE 3: Audit Log — append-only record of every status change
        # Unlike updated_at (which overwrites), this preserves FULL history.
        # Compliance requirement: survives app restarts, supports auditing.
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS ticket_logs (
                log_id      INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id   INTEGER NOT NULL,
                old_status  TEXT    NOT NULL,
                new_status  TEXT    NOT NULL,
                changed_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (ticket_id) REFERENCES tickets(ticket_id)
            )
        ''')

        # PERFORMANCE INDICES — B-tree: O(log n) vs O(n) full table scan
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_tickets_status   ON tickets(status)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_tickets_priority ON tickets(priority)')

        # SEED DATA — INSERT OR IGNORE: safe to rerun, skips duplicates
        departments = [(DEPT_IT,), (DEPT_BILLING,), (DEPT_HR,), (DEPT_GENERAL,)]
        cursor.executemany(
            'INSERT OR IGNORE INTO departments (dept_name) VALUES (?)',
            departments
        )

        conn.commit()
        print("[*] Database Initialized: 3-table normalized schema + B-tree indices ready.")

    except sqlite3.Error as e:
        conn.rollback()
        print(f"[-] FATAL setup error: {e}")

# ── RUN SETUP ──
db = get_connection()
initialize_database(db)


# In[2]:


def analyze_ticket(text_to_analyze: str) -> Tuple[str, str, str]:
    """
    Deterministic, rule-based routing engine.
    Two INDEPENDENT if/elif blocks:
      Block 1 → WHO handles it (category + department)
      Block 2 → HOW URGENT it is (priority)
    First matching rule wins. Analyzes title + description combined.
    Returns: (category, priority, dept_name)
    """
    text_lower = text_to_analyze.lower()

    # ── Block 1: WHO handles it? ──
    if any(w in text_lower for w in ['server', 'network', 'login', 'password', 'system']):
        category, dept_name = "Technical",       DEPT_IT
    elif any(w in text_lower for w in ['invoice', 'charge', 'payment', 'refund']):
        category, dept_name = "Billing",         DEPT_BILLING
    elif any(w in text_lower for w in ['leave', 'payroll', 'manager', 'policy']):
        category, dept_name = "HR",              DEPT_HR
    else:
        category, dept_name = "General Inquiry", DEPT_GENERAL

    # ── Block 2: HOW URGENT? (independent of category above) ──
    if any(w in text_lower for w in ['urgent', 'crash', 'down', 'immediately', 'critical']):
        priority = "Critical"
    elif any(w in text_lower for w in ['error', 'issue', 'unable', 'fail', 'blocked']):
        priority = "High"
    elif any(w in text_lower for w in ['request', 'need', 'clarify']):
        priority = "Medium"
    else:
        priority = "Low"

    return category, priority, dept_name


def get_department_id(conn: sqlite3.Connection, dept_name: str) -> int:
    """
    Translates department NAME → database ID number.
    3-level protection:
      Level 1 → Find the exact department
      Level 2 → Fall back to 'General' if not found
      Level 3 → Raise ValueError loudly if even General is missing
    """
    cursor = conn.cursor()

    cursor.execute('SELECT dept_id FROM departments WHERE dept_name = ?', (dept_name,))
    result = cursor.fetchone()
    if result:
        return result[0]

    # Fallback
    cursor.execute('SELECT dept_id FROM departments WHERE dept_name = ?', (DEPT_GENERAL,))
    fallback = cursor.fetchone()
    if fallback is None:
        raise ValueError(f"FATAL: '{DEPT_GENERAL}' department missing. Database may be corrupt.")
    return fallback[0]


# In[3]:


# ══════════════════════
# CREATE
# ══════════════════════
def submit_ticket(conn: sqlite3.Connection, title: str, description: str) -> Optional[int]:
    """
    Validates → routes → inserts a new ticket.
    - Strips whitespace before validation
    - Combines title + description for routing accuracy
    - '?' placeholders = SQL injection prevention
    - Returns lastrowid: the actual DB-assigned ID
    """
    title       = title.strip()
    description = description.strip()

    if not title or not description:
        print("[-] Error: Title and Description cannot be empty.")
        return None

    category, priority, dept_name = analyze_ticket(title + " " + description)
    dept_id = get_department_id(conn, dept_name)

    try:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO tickets (title, description, category, priority, dept_id)
            VALUES (?, ?, ?, ?, ?)
        ''', (title, description, category, priority, dept_id))
        conn.commit()
        ticket_id = cursor.lastrowid
        print(f"[+] Ticket Created: ID {ticket_id} | '{title}' → {dept_name} [{priority}]")
        return ticket_id

    except sqlite3.Error as e:
        conn.rollback()
        print(f"[-] Insertion error: {e}")
        return None


# ══════════════════════
# UPDATE — State Machine + Atomic Audit Log
# ══════════════════════
def update_ticket_status(conn: sqlite3.Connection, ticket_id: int, new_status: str) -> None:
    """
    3-step process:
      Step 1 → SELECT: verify ticket exists + get current status
      Step 2 → VALIDATE: check VALID_TRANSITIONS state machine
      Step 3 → WRITE: UPDATE tickets + INSERT ticket_logs in ONE transaction
    Both writes share a single conn.commit() — fully atomic.
    """
    try:
        cursor = conn.cursor()

        # Step 1: Verify + fetch current state
        cursor.execute('SELECT status FROM tickets WHERE ticket_id = ?', (ticket_id,))
        row = cursor.fetchone()
        if not row:
            print(f"[-] Error: Ticket ID {ticket_id} not found.")
            return

        current_status = row[0]

        # Step 2: State machine check
        if new_status not in VALID_TRANSITIONS.get(current_status, []):
            print(f"[-] Invalid Transition: '{current_status}' → '{new_status}' not permitted.")
            return

        # Step 3a: Update the ticket
        cursor.execute('''
            UPDATE tickets
            SET    status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE  ticket_id = ?
        ''', (new_status, ticket_id))

        # Step 3b: Write to audit log — SAME transaction, before commit
        cursor.execute('''
            INSERT INTO ticket_logs (ticket_id, old_status, new_status)
            VALUES (?, ?, ?)
        ''', (ticket_id, current_status, new_status))

        # Single commit — both writes succeed or both roll back
        conn.commit()
        print(f"[*] Ticket {ticket_id}: '{current_status}' → '{new_status}' [logged]")

    except sqlite3.Error as e:
        conn.rollback()
        print(f"[-] Update error: {e}")


# ══════════════════════
# DELETE — The "D" in CRUD
# ══════════════════════
def delete_ticket(conn: sqlite3.Connection, ticket_id: int) -> None:
    """
    Verifies existence before deleting. Never runs a blind DELETE.
    Note: Tickets with audit log entries cannot be deleted
    (FK constraint protects audit integrity — by design).
    """
    try:
        cursor = conn.cursor()
        cursor.execute('SELECT ticket_id FROM tickets WHERE ticket_id = ?', (ticket_id,))
        if not cursor.fetchone():
            print(f"[-] Error: Ticket ID {ticket_id} not found.")
            return

        cursor.execute('DELETE FROM tickets WHERE ticket_id = ?', (ticket_id,))
        conn.commit()
        print(f"[!] Ticket {ticket_id} permanently deleted.")

    except sqlite3.Error as e:
        conn.rollback()
        print(f"[-] Deletion error: {e}")


# ══════════════════════
# RESET — Jupyter helper ONLY
# ══════════════════════
def reset_tickets(conn: sqlite3.Connection) -> None:
    """
    Clears ALL ticket data and resets ID counters.
    IMPORTANT: Deletes ticket_logs FIRST (child), then tickets (parent).
    FK constraint prevents deleting parents before children.
    Remove this function from main.py — testing only.
    """
    try:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM ticket_logs')          # Children first
        cursor.execute('DELETE FROM tickets')              # Then parents
        cursor.execute("DELETE FROM sqlite_sequence WHERE name='ticket_logs'")
        cursor.execute("DELETE FROM sqlite_sequence WHERE name='tickets'")
        conn.commit()
        print("[!] All tickets + audit logs cleared. ID counters reset to 1.")

    except sqlite3.Error as e:
        conn.rollback()
        print(f"[-] Reset error: {e}")


# In[4]:


# ══════════════════════
# DYNAMIC FILTER
# ══════════════════════
def filter_tickets(conn: sqlite3.Connection,
                   status: str = None,
                   priority: str = None) -> None:
    """
    WHERE 1=1 pattern: always true, lets you append AND clauses cleanly.
    params list cast to tuple before execution (sqlite3 driver requirement).
    """
    query = '''
        SELECT t.ticket_id, t.title, t.status, t.priority, d.dept_name, t.updated_at
        FROM   tickets t
        JOIN   departments d ON t.dept_id = d.dept_id
        WHERE  1=1
    '''
    params = []

    if status:
        query += ' AND t.status = ?'
        params.append(status)
    if priority:
        query += ' AND t.priority = ?'
        params.append(priority)

    cursor = conn.cursor()
    cursor.execute(query, tuple(params))   # list → tuple for driver safety

    status_str   = status   if status   else "All"
    priority_str = priority if priority else "All"
    print(f"\n--- Tickets | Status: {status_str} | Priority: {priority_str} ---")

    rows = cursor.fetchall()
    if not rows:
        print("   No tickets match the given filters.")
        return
    for row in rows:
        print(f"   ID:{row[0]} | {row[1]:<20} | {row[4]:<12} | {row[3]:<8} | {row[2]:<12} | Updated: {row[5]}")


# ══════════════════════
# TEXT SEARCH
# ══════════════════════
def search_tickets(conn: sqlite3.Connection, keyword: str) -> None:
    """
    %keyword% = contains match anywhere in the string.
    JOINs departments to show routing context alongside results.
    """
    search_term = f"%{keyword}%"
    cursor = conn.cursor()
    cursor.execute('''
        SELECT t.ticket_id, t.title, t.status, d.dept_name
        FROM   tickets t
        JOIN   departments d ON t.dept_id = d.dept_id
        WHERE  t.title LIKE ? OR t.description LIKE ?
    ''', (search_term, search_term))

    rows = cursor.fetchall()
    print(f"\n--- Search: '{keyword}' ---")
    if not rows:
        print("   No matching tickets found.")
        return
    for row in rows:
        print(f"   ID:{row[0]} | {row[1]:<20} | {row[3]:<12} | Status: {row[2]}")


# ══════════════════════
# 3-PART REPORTS
# ══════════════════════
def generate_reports(conn: sqlite3.Connection) -> None:
    """
    Report 1: LEFT JOIN — keeps depts with zero tickets visible
              (INNER JOIN would silently hide them — a data bug)
    Report 2: GROUP BY + COUNT — priority distribution
    Report 3: Filter in ON clause (NOT WHERE) — preserves LEFT JOIN
              (WHERE clause converts LEFT JOIN → INNER JOIN)
    """
    cursor = conn.cursor()
    print("\n========== OPERATIONAL REPORTS ==========")

    print("\n1. Workload by Department (LEFT JOIN):")
    cursor.execute('''
        SELECT   d.dept_name, COUNT(t.ticket_id) AS total
        FROM     departments d
        LEFT JOIN tickets t ON d.dept_id = t.dept_id
        GROUP BY d.dept_name
        ORDER BY total DESC
    ''')
    for row in cursor.fetchall():
        print(f"   {row[0]:<15}: {row[1]} ticket(s)")

    print("\n2. Ticket Count by Priority (GROUP BY):")
    cursor.execute('''
        SELECT   priority, COUNT(*) AS count
        FROM     tickets
        GROUP BY priority
        ORDER BY count DESC
    ''')
    rows = cursor.fetchall()
    if not rows:
        print("   No tickets found.")
    for row in rows:
        print(f"   {row[0]:<15}: {row[1]} ticket(s)")

    print("\n3. Open Tickets per Department (filter in ON clause):")
    cursor.execute('''
        SELECT   d.dept_name, COUNT(t.ticket_id) AS open_count
        FROM     departments d
        LEFT JOIN tickets t ON d.dept_id = t.dept_id AND t.status = 'Open'
        GROUP BY d.dept_name
        ORDER BY open_count DESC
    ''')
    for row in cursor.fetchall():
        print(f"   {row[0]:<15}: {row[1]} open")


# ══════════════════════
# AUDIT TRAIL VIEWER
# ══════════════════════
def get_audit_trail(conn: sqlite3.Connection, ticket_id: int) -> None:
    """
    Retrieves the complete lifecycle history of a single ticket.
    3-table JOIN: ticket_logs → tickets → (dept shown via tickets)
    Unlike updated_at, this is append-only: shows every transition ever made.
    """
    cursor = conn.cursor()
    cursor.execute('''
        SELECT   l.log_id, t.title, l.old_status, l.new_status, l.changed_at
        FROM     ticket_logs l
        JOIN     tickets t ON l.ticket_id = t.ticket_id
        WHERE    l.ticket_id = ?
        ORDER BY l.changed_at ASC
    ''', (ticket_id,))

    rows = cursor.fetchall()
    print(f"\n--- Audit Trail: Ticket {ticket_id} ---")
    if not rows:
        print("   No transitions recorded for this ticket.")
        return
    for row in rows:
        print(f"   [Log {row[0]}] '{row[1]}': {row[2]} → {row[3]}  ({row[4]})")


# In[7]:


# ══════════════════════════════════════════════════
#  FULL SYSTEM DEMO
#  Rerun-safe: db stays open, IDs reset cleanly.
#  db.close() intentionally omitted — Jupyter stays
#  live between runs. Add it only in main.py bottom.
# ══════════════════════════════════════════════════

# ── 1. Clean slate ──

# ── 2. Create tickets (IDs captured dynamically from DB) ──
print("\n--- Submitting New Tickets ---")
id1 = submit_ticket(db, "System Outage",    "Production server is down. Users cannot login. Urgent crash.")
id2 = submit_ticket(db, "Duplicate Charge", "Need refund for duplicate charge on my invoice.")
id3 = submit_ticket(db, "Sick Leave",       "I need sick leave policy clarification request.")
id4 = submit_ticket(db, "Password Reset",   "Forgot system password, unable to access the portal.")

# ── 3. State Machine tests ──
print("\n--- Testing State Machine ---")
update_ticket_status(db, id1, 'In Progress')   # ✅ Open → In Progress (logged)
update_ticket_status(db, id2, 'Resolved')       # ✅ Open → Resolved (logged)
update_ticket_status(db, id2, 'In Progress')    # ❌ Blocked: Resolved is terminal
update_ticket_status(db, 999, 'Resolved')        # ❌ Blocked: ID not found

# ── 4. Delete test ──
# Note: id4 has no log entries (never updated) so FK allows deletion.
# Tickets WITH log entries (id1, id2) are FK-protected from deletion.
print("\n--- Testing Delete (D in CRUD) ---")
delete_ticket(db, id4)

# ── 5. Query data ──
filter_tickets(db)                              # All remaining tickets
filter_tickets(db, status="Open")              # Only Open
filter_tickets(db, priority="Critical")        # Only Critical
search_tickets(db, "password")                 # Text search

# ── 6. Audit trail — shows complete lifecycle history ──
print("\n--- Audit Trail Verification ---")
get_audit_trail(db, id1)   # Should show: Open → In Progress
get_audit_trail(db, id2)   # Should show: Open → Resolved

# ── 7. Analytics ──
generate_reports(db)


# In[ ]:




# Close connection cleanly when running as a terminal script
db.close()
print("[*] Connection closed cleanly.")
