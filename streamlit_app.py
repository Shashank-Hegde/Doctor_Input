import streamlit as st
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo

import gspread
from google.oauth2.service_account import Credentials


# ---------------------- CONFIG ----------------------

# Simple login (you can change username/password)
VALID_USERS = {
    "engineer": "engineer123",
}

# Data entry columns (edit these as needed)
COLUMNS = ["col1", "col2", "col3", "col4"]

# Blank rows shown for entry
DEFAULT_ROWS = 10

TIMEZONE = "Asia/Kolkata"


# ---------------------- HELPERS ----------------------

@st.cache_resource
def get_gspread_client():
    """Create a cached gspread client."""
    service_info = dict(st.secrets["gcp_service_account"])
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(service_info, scopes=scopes)
    return gspread.authorize(creds)


def get_spreadsheet():
    client = get_gspread_client()
    spreadsheet_id = st.secrets["SPREADSHEET_ID"]
    return client.open_by_key(spreadsheet_id)


def get_today_sheet():
    """Get or create today's worksheet named data_YYYY-MM-DD."""
    sh = get_spreadsheet()
    now = datetime.now(ZoneInfo(TIMEZONE))
    sheet_name = f"data_{now.strftime('%Y-%m-%d')}"

    try:
        ws = sh.worksheet(sheet_name)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=sheet_name, rows="2000", cols=str(len(COLUMNS)))
        ws.append_row(COLUMNS)

    return ws


def append_rows(ws, df):
    """Append non-empty rows from df to worksheet."""
    df_clean = df.dropna(how="all")
    if df_clean.empty:
        return 0

    rows = df_clean.values.tolist()
    for r in rows:
        ws.append_row(r, value_input_option="USER_ENTERED")
    return len(rows)


def get_date_sheets():
    """Return list of (date_str, worksheet) sorted by date descending."""
    sh = get_spreadsheet()
    worksheets = sh.worksheets()

    date_sheets = []
    for ws in worksheets:
        if ws.title.startswith("data_"):
            date_str = ws.title.replace("data_", "", 1)
            try:
                d = datetime.strptime(date_str, "%Y-%m-%d")
                date_sheets.append((d, date_str, ws))
            except ValueError:
                continue

    date_sheets.sort(key=lambda x: x[0], reverse=True)
    return [(date_str, ws) for (_, date_str, ws) in date_sheets]


# ---------------------- LOGIN PAGE ----------------------

def login_page():
    st.title("Secure Login")

    username = st.text_input("Username")
    password = st.text_input("Password", type="password")
    login_btn = st.button("Login")

    if login_btn:
        if username in VALID_USERS and VALID_USERS[username] == password:
            st.session_state["logged_in"] = True
            st.rerun()
        else:
            st.error("Invalid username or password")


# ---------------------- HISTORY (LEFT SIDE) ----------------------

def history_section():
    st.subheader("Previous Entries (Read-only)")

    # CSS: disable text selection + hide toolbar/download
    st.markdown(
        """
        <style>
        .no-select * {
            -webkit-user-select: none;
            -moz-user-select: none;
            -ms-user-select: none;
            user-select: none;
        }
        /* Hide toolbar (includes CSV download) on all dataframes/editors */
        [data-testid="stElementToolbar"] {
            display: none !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    date_sheets = get_date_sheets()
    if not date_sheets:
        st.write("No previous data yet.")
        return

    date_labels = [d for (d, _) in date_sheets]

    selected_date = st.radio("Select a date to view:", date_labels, index=0)

    # Find worksheet for selected date
    selected_ws = None
    for d, ws in date_sheets:
        if d == selected_date:
            selected_ws = ws
            break

    if not selected_ws:
        st.write("No data for this date.")
        return

    rows = selected_ws.get_all_values()
    if not rows or len(rows) <= 1:
        st.write("No rows submitted for this date.")
        return

    header = rows[0]
    data_rows = rows[1:]
    df = pd.DataFrame(data_rows, columns=header)

    st.markdown(f"Showing data for **{selected_date}**:")
    st.markdown('<div class="no-select">', unsafe_allow_html=True)
    st.dataframe(df, use_container_width=True)
    st.markdown('</div>', unsafe_allow_html=True)


# ---------------------- DATA ENTRY (RIGHT SIDE) ----------------------

def data_entry_section():
    st.subheader("New Data Entry (Write-Only)")

    st.write(
        "Enter rows below. After you click **Submit**, the table is cleared. "
        "Previous entries can only be viewed on the left as read-only."
    )

    if "input_df" not in st.session_state:
        st.session_state["input_df"] = pd.DataFrame(
            [["" for _ in COLUMNS] for _ in range(DEFAULT_ROWS)],
            columns=COLUMNS,
        )

    # CSS: hide toolbar/download on editor as well
    st.markdown(
        """
        <style>
        [data-testid="stElementToolbar"] {
            display: none !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    edited = st.data_editor(
        st.session_state["input_df"],
        num_rows="dynamic",
        hide_index=True,
        use_container_width=True,
    )

    col1, col2 = st.columns(2)

    with col1:
        submit = st.button("Submit to Google Sheet", type="primary")

    with col2:
        clear = st.button("Clear Table")

    if clear:
        st.session_state["input_df"] = pd.DataFrame(
            [["" for _ in COLUMNS] for _ in range(DEFAULT_ROWS)],
            columns=COLUMNS,
        )
        st.rerun()

    if submit:
        try:
            ws = get_today_sheet()
            saved_rows = append_rows(ws, edited)

            if saved_rows == 0:
                st.warning("No non-empty rows to save.")
            else:
                st.success(f"Saved {saved_rows} rows to today's sheet.")

                # Immediately clear the table, then rerun
                st.session_state["input_df"] = pd.DataFrame(
                    [["" for _ in COLUMNS] for _ in range(DEFAULT_ROWS)],
                    columns=COLUMNS,
                )
                st.rerun()
        except Exception as e:
            st.error(f"Error: {e}")


# ---------------------- MAIN APP ----------------------

def main():
    st.set_page_config(page_title="Doctor Input Portal", layout="wide")

    if "logged_in" not in st.session_state:
        st.session_state["logged_in"] = False

    if not st.session_state["logged_in"]:
        login_page()
        return

    with st.sidebar:
        st.write("Logged in as: **engineer**")
        if st.button("Logout"):
            st.session_state.clear()
            st.rerun()

    st.title("Doctor Input Portal")

    # Two-column layout: left = history, right = entry
    left_col, right_col = st.columns([1, 2])

    with left_col:
        history_section()

    with right_col:
        data_entry_section()


if __name__ == "__main__":
    main()
