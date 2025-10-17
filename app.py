# app.py
import streamlit as st
import sqlite3
import pandas as pd
from datetime import date
import hashlib
import plotly.express as px
import uuid

# =========================
# Config
# =========================
st.set_page_config(page_title="Central To-Do Planner", layout="wide")
DB_PATH = "tasks.db"

# =========================
# Helpers: hashing
# =========================
def make_hash(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def check_hash(password: str, hashed: str) -> bool:
    return make_hash(password) == hashed

# =========================
# DB Setup
# =========================
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
c = conn.cursor()

# Users table
c.execute("""
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE,
    password TEXT,
    role TEXT CHECK(role IN ('admin','user')) NOT NULL DEFAULT 'user'
)
""")

# Tasks table
c.execute("""
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task TEXT,
    assigned_to TEXT,
    given_by TEXT,
    priority TEXT,
    status TEXT,
    start_date DATE,
    end_date DATE,
    progress INTEGER,
    comments TEXT,
    admin_comments TEXT,
    recurrence TEXT DEFAULT 'None',
    recurrence_until DATE,
    series_id TEXT
)
""")
conn.commit()

# Bootstrap admin
c.execute("SELECT COUNT(*) FROM users")
if c.fetchone()[0] == 0:
    c.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
              ("admin", make_hash("admin123"), "admin"))
    conn.commit()

# =========================
# Session helpers
# =========================
def do_login(username: str):
    st.session_state.logged_in = True
    st.session_state.username = username
    c.execute("SELECT role FROM users WHERE username=?", (username,))
    row = c.fetchone()
    st.session_state.role = row[0] if row else "user"

def do_logout():
    st.session_state.clear()

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

# =========================
# Scoring
# =========================
def compute_scores(username=None):
    if username:
        df_user = pd.read_sql("SELECT * FROM tasks WHERE assigned_to=?", conn, params=(username,))
    else:
        df_user = pd.read_sql("SELECT * FROM tasks", conn)

    if df_user.empty:
        return None

    total = len(df_user)
    completed = (df_user["status"] == "Completed").sum()
    on_time = len(df_user[(df_user["status"] == "Completed") &
                          (pd.to_datetime(df_user["end_date"]) >= pd.to_datetime(df_user["start_date"]))])
    avg_progress = float(df_user["progress"].mean()) if total > 0 else 0.0

    completion_rate = (completed / total) * 100 if total > 0 else 0.0
    ontime_rate = (on_time / total) * 100 if total > 0 else 0.0
    score = round(0.5 * completion_rate + 0.3 * ontime_rate + 0.2 * avg_progress, 2)

    return {
        "Total Tasks": total,
        "Completion %": completion_rate,
        "On-time %": ontime_rate,
        "Avg Progress %": avg_progress,
        "Efficiency Score": score
    }

def render_kpis(metrics, labels=("Total", "Completion %", "On-time %", "Avg Progress", "Efficiency")):
    if not metrics:
        return
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric(labels[0], metrics["Total Tasks"])
    col2.metric(labels[1], f"{metrics['Completion %']:.1f}%")
    col3.metric(labels[2], f"{metrics['On-time %']:.1f}%")
    col4.metric(labels[3], f"{metrics['Avg Progress %']:.1f}%")
    col5.metric(labels[4], metrics["Efficiency Score"])

# =========================
# Visualization Helpers
# =========================
def fig_status_pie(df, title="Task Status Distribution"):
    if df.empty:
        return None
    return px.pie(df, names="status", title=title)

def fig_priority_bar(df, title="Tasks by Priority"):
    if df.empty:
        return None
    pr_counts = df.groupby("priority").size().reset_index(name="count")
    return px.bar(pr_counts, x="priority", y="count", color="priority", title=title)

def fig_progress_trend(df, title="Progress Trend Over Time"):
    if df.empty or "start_date" not in df.columns:
        return None
    tmp = df.copy()
    tmp["start_date"] = pd.to_datetime(tmp["start_date"])
    trend = tmp.groupby("start_date")["progress"].mean().reset_index()
    if trend.empty:
        return None
    return px.line(trend, x="start_date", y="progress", title=title)

def fig_calendar_heatmap(df, title="Task Calendar Heatmap"):
    if df.empty:
        return None
    tmp = df.copy()
    tmp["start_date"] = pd.to_datetime(tmp["start_date"])
    counts = tmp.groupby(tmp["start_date"].dt.date).size().reset_index(name="count")
    counts = counts.sort_values("start_date")
    return px.bar(counts, x="start_date", y="count", title=title)

def fig_gantt(df, title="All Tasks Timeline"):
    if df.empty:
        return None
    tmp = df.copy()
    tmp["start_date"] = pd.to_datetime(tmp["start_date"])
    tmp["end_date"] = pd.to_datetime(tmp["end_date"])
    tmp.loc[tmp["end_date"] < tmp["start_date"], "end_date"] = tmp["start_date"]
    fig = px.timeline(tmp, x_start="start_date", x_end="end_date", y="assigned_to",
                      color="status", title=title, hover_data=["task", "priority"])
    fig.update_yaxes(autorange="reversed")
    return fig

# =========================
# UI Helpers
# =========================
def show_task_card(row):
    bg_color = "#f0f0f0"
    if row["status"] == "Completed":
        bg_color = "#d4edda"
    else:
        try:
            if row["end_date"] and pd.to_datetime(row["end_date"]) < pd.to_datetime("today") and row["status"] != "Completed":
                bg_color = "#f8d7da"
        except Exception:
            pass
        if row["status"] == "In Progress":
            bg_color = "#fff3cd"

    border_color = {"High": "red", "Medium": "orange", "Low": "steelblue"}.get(row["priority"], "#ccc")

    st.markdown(f"""
    <div style="padding:10px; border-radius:10px; background-color:{bg_color};
                border: 3px solid {border_color}; margin-bottom:10px;">
      <b>Task:</b> {row['task']}<br>
      <b>Status:</b> {row['status']}<br>
      <b>Progress:</b> {row['progress']}%<br>
      <b>Start:</b> {row['start_date']} — <b>End:</b> {row['end_date']}<br>
      <b>Priority:</b> {row['priority']}<br>
      <b>Comments:</b> {row['comments'] or ''}<br>
      <b>Admin Notes:</b> {row['admin_comments'] or ''}<br>
      <b>Recurrence:</b> {row['recurrence'] or 'None'}<br>
    </div>
    """, unsafe_allow_html=True)

def auto_populate_recurrences(task, assigned_to, given_by, priority, status,
                              start_date, end_date, progress, comments,
                              recurrence, recurrence_until, series_id):
    if recurrence == "None" or not recurrence_until:
        return
    next_start = pd.to_datetime(start_date)
    next_end = pd.to_datetime(end_date)
    until = pd.to_datetime(recurrence_until)

    while True:
        if recurrence == "Daily":
            next_start += pd.Timedelta(days=1)
            next_end += pd.Timedelta(days=1)
        elif recurrence == "Weekly":
            next_start += pd.Timedelta(weeks=1)
            next_end += pd.Timedelta(weeks=1)
        elif recurrence == "Monthly":
            next_start += pd.DateOffset(months=1)
            next_end += pd.DateOffset(months=1)
        else:
            break

        if next_start.date() > until.date():
            break

        c.execute("""INSERT INTO tasks
                     (task,assigned_to,given_by,priority,status,start_date,end_date,progress,comments,
                      recurrence,recurrence_until,series_id)
                     VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (task, assigned_to, given_by, priority, "Not Started",
                   next_start.date().isoformat(), next_end.date().isoformat(), 0, comments,
                   recurrence, recurrence_until, series_id))
    conn.commit()

# =========================
# Dashboards
# =========================
def show_user_dashboard():
    st.sidebar.markdown("---")
    st.sidebar.write(f"👤 **{st.session_state.username}** (User)")
    if st.sidebar.button("Logout"):
        do_logout()
        st.rerun()

    st.title("👤 My Tasks")

    # KPIs
    render_kpis(compute_scores(st.session_state.username))

    # Personal Calendar
    df_me_all = pd.read_sql("SELECT * FROM tasks WHERE assigned_to=?", conn, params=(st.session_state.username,))
    fig_cal = fig_calendar_heatmap(df_me_all, title="📅 My Task Calendar")
    if fig_cal:
        st.plotly_chart(fig_cal, use_container_width=True)

    # Add Task
    with st.form("task_form", clear_on_submit=True):
        colA, colB = st.columns(2)
        with colA:
            task = st.text_input("Task")
            given_by = st.text_input("Given By")
            priority = st.selectbox("Priority", ["High", "Medium", "Low"])
            status = st.selectbox("Status", ["Not Started", "In Progress", "Completed"])
        with colB:
            start_date_val = st.date_input("Start Date", date.today())
            end_date_val = st.date_input("End Date", min_value=start_date_val)
            progress_val = st.slider("Progress %", 0, 100, 0)
            comments = st.text_area("Comments")
            recurrence = st.selectbox("Recurring?", ["None", "Daily", "Weekly", "Monthly"])
            recurrence_until = None
            if recurrence != "None":
                recurrence_until = st.date_input("Repeat Until", date.today().replace(year=date.today().year + 1))

        submitted = st.form_submit_button("Add Task")
        if submitted and task:
            series_id = str(uuid.uuid4()) if recurrence != "None" else None
            c.execute("""INSERT INTO tasks
                         (task,assigned_to,given_by,priority,status,start_date,end_date,progress,comments,
                          recurrence,recurrence_until,series_id)
                         VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (task, st.session_state.username, given_by, priority, status,
                       start_date_val.isoformat(), end_date_val.isoformat(), int(progress_val), comments,
                       recurrence, recurrence_until.isoformat() if recurrence_until else None, series_id))
            conn.commit()

            if recurrence != "None" and recurrence_until:
                auto_populate_recurrences(
                    task, st.session_state.username, given_by, priority, status,
                    start_date_val, end_date_val, progress_val, comments,
                    recurrence, recurrence_until.isoformat(), series_id
                )

            st.success("✅ Task(s) Added")
            st.rerun()

    # Display tasks
    df = pd.read_sql("SELECT * FROM tasks WHERE assigned_to=?", conn, params=(st.session_state.username,))
    if df.empty:
        st.info("You have no tasks yet.")
    else:
        grouped = df.groupby("series_id", dropna=False, sort=False)
        for sid, group in grouped:
            if pd.isna(sid):
                show_task_card(group.iloc[0])
            else:
                with st.expander(f"🔁 Recurring Series: {group.iloc[0]['task']} ({group.iloc[0]['recurrence']})"):
                    for _, row in group.sort_values("start_date").iterrows():
                        show_task_card(row)

def show_admin_dashboard():
    st.sidebar.markdown("---")
    st.sidebar.write(f"🛠️ **{st.session_state.username}** (Admin)")
    if st.sidebar.button("Logout"):
        do_logout()
        st.rerun()

    st.title("🛠️ Admin Dashboard")

    df = pd.read_sql("SELECT * FROM tasks", conn)
    if df.empty:
        st.info("No tasks available.")
        return

    render_kpis(compute_scores())

    st.subheader("📊 Global Visualizations")
    col1, col2 = st.columns(2)
    fig1 = fig_status_pie(df, "Task Status Distribution (All)")
    fig2 = fig_priority_bar(df, "Tasks by Priority (All)")
    if fig1: col1.plotly_chart(fig1, use_container_width=True)
    if fig2: col2.plotly_chart(fig2, use_container_width=True)

    fig3 = fig_progress_trend(df, "Average Progress Trend (All)")
    if fig3: st.plotly_chart(fig3, use_container_width=True)

    st.subheader("📅 Scheduling Views")
    fig_cal_all = fig_calendar_heatmap(df, "Task Calendar (All Users)")
    if fig_cal_all: st.plotly_chart(fig_cal_all, use_container_width=True)

    fig_g = fig_gantt(df, "All Tasks Timeline (Gantt)")
    if fig_g: st.plotly_chart(fig_g, use_container_width=True)

    st.subheader("🏆 Efficiency Leaderboard")
    users = pd.read_sql("SELECT DISTINCT username FROM users WHERE role='user'", conn)["username"].tolist()
    leaderboard = []
    for u in users:
        m = compute_scores(u)
        if m:
            leaderboard.append({"User": u, **m})
    if leaderboard:
        df_leader = pd.DataFrame(leaderboard).sort_values("Efficiency Score", ascending=False)
        st.dataframe(df_leader, use_container_width=True)
    else:
        st.info("No user data yet.")

    st.subheader("👤 User Detail View")
    selected_user = st.selectbox("Select a user", users)
    if selected_user:
        render_kpis(compute_scores(selected_user), labels=("Total (User)", "Completion %", "On-time %", "Avg Progress", "Efficiency"))

        df_user = pd.read_sql("SELECT * FROM tasks WHERE assigned_to=?", conn, params=(selected_user,))
        if df_user.empty:
            st.info("No tasks for this user.")
            return

        colu1, colu2 = st.columns(2)
        u1 = fig_status_pie(df_user, f"Status Distribution — {selected_user}")
        u2 = fig_priority_bar(df_user, f"Tasks by Priority — {selected_user}")
        if u1: colu1.plotly_chart(u1, use_container_width=True)
        if u2: colu2.plotly_chart(u2, use_container_width=True)

        u3 = fig_progress_trend(df_user, f"Progress Trend — {selected_user}")
        if u3: st.plotly_chart(u3, use_container_width=True)

        u_cal = fig_calendar_heatmap(df_user, f"Task Calendar — {selected_user}")
        if u_cal: st.plotly_chart(u_cal, use_container_width=True)

        grouped = df_user.groupby("series_id", dropna=False, sort=False)
        for sid, group in grouped:
            if pd.isna(sid):
                with st.expander(f"Task {group.iloc[0]['id']} - {group.iloc[0]['task']}"):
                    show_task_card(group.iloc[0])
                    row = group.iloc[0]
                    admin_note = st.text_area("✏️ Admin comment", row.get("admin_comments", ""), key=f"adm_single_{row['id']}")
                    if st.button("Save Comment", key=f"save_single_{row['id']}"):
                        c.execute("UPDATE tasks SET admin_comments=? WHERE id=?", (admin_note, row["id"]))
                        conn.commit()
                        st.success("Comment saved ✅")
                        st.rerun()
            else:
                with st.expander(f"🔁 Recurring Series: {group.iloc[0]['task']} ({group.iloc[0]['recurrence']})"):
                    current_series_note = (group["admin_comments"].dropna().iloc[0]
                                           if group["admin_comments"].dropna().size > 0 else "")
                    admin_series_note = st.text_area("✏️ Series-level admin note (applies to all tasks)", current_series_note, key=f"series_{sid}")
                    if st.button("Save Series Note", key=f"save_series_{sid}"):
                        c.execute("UPDATE tasks SET admin_comments=? WHERE series_id=?", (admin_series_note, sid))
                        conn.commit()
                        st.success("Series note updated ✅")
                        st.rerun()

                    for _, row in group.sort_values("start_date").iterrows():
                        show_task_card(row)

# =========================
# Auth UI
# =========================
if not st.session_state.logged_in:
    st.sidebar.title("🔑 Login / Signup")
    auth_tab = st.sidebar.radio("Account", ["Login", "Sign Up"])

    if auth_tab == "Sign Up":
        st.title("Create Account")
        new_user = st.text_input("Username", key="su_user")
        new_pass = st.text_input("Password", type="password", key="su_pass")
        new_role = st.radio("Role", ["user", "admin"], key="su_role", horizontal=True)
        if st.button("Sign Up"):
            if not new_user or not new_pass:
                st.error("Please enter a username and password.")
            else:
                try:
                    c.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                              (new_user, make_hash(new_pass), new_role))
                    conn.commit()
                    st.success(f"✅ {new_role.capitalize()} account created! Please login.")
                except sqlite3.IntegrityError:
                    st.error("⚠️ Username already exists.")
    else:
        st.title("Login")
        username = st.text_input("Username", key="li_user")
        password = st.text_input("Password", type="password", key="li_pass")
        if st.button("Login"):
            c.execute("SELECT username, password, role FROM users WHERE username=?", (username,))
            row = c.fetchone()
            if row and check_hash(password, row[1]):
                do_login(username)
                st.success(f"✅ Logged in as {username} ({row[2]})")
                st.rerun()
            else:
                st.error("❌ Invalid username or password.")
else:
    if st.session_state.role == "user":
        show_user_dashboard()
    elif st.session_state.role == "admin":
        show_admin_dashboard()
