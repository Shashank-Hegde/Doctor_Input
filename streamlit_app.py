import streamlit as st
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo

import gspread
from google.oauth2.service_account import Credentials


# ---------------------- CONFIG ----------------------

# Simple login (adjust as needed)
VALID_USERS = {
    "engineer": "engineer123",
}

# Data entry columns
COLUMNS = ["col1", "col2", "col3", "col4"]

# Number of blank rows to show
DEFAULT_ROWS = 10

TIMEZONE = "Asia/Kolkata"


# ---------------------- GOOGLE SHEETS HELPERS ----------------------

@st.cache_resource
def get_gspread_client():
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


def append_rows(ws, df: pd.DataFrame) -> int:
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
    # Return just (date_str, ws)
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


# ---------------------- PREVIOUS ENTRIES TAB ----------------------

def history_tab():
    st.subheader("Previous Entries (Read-only)")

    # Global CSS:
    #  - hide the little toolbar (download, etc.)
    #  - prevent selection & pointer events on the history table
    st.markdown(
        """
        <style>
        /* Hide toolbar on all tables/editors */
        [data-testid="stElementToolbar"] {
            display: none !important;
        }
        /* Make the history table non-interactive and non-selectable */
        .no-select-table * {
            -webkit-user-select: none;
            -moz-user-select: none;
            -ms-user-select: none;
            user-select: none;
        }
        .no-select-table [data-testid="stDataFrame"] {
            pointer-events: none;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    date_sheets = get_date_sheets()
    if not date_sheets:
        st.write("No previous data yet.")
        return

    date_options = ["None"] + [d for (d, _) in date_sheets]
    selected = st.selectbox("Select a date to view:", date_options, index=0)

    if selected == "None":
        st.info("Select a date above to view previous submissions.")
        return

    # Find the worksheet for the selected date
    ws = None
    for d, w in date_sheets:
        if d == selected:
            ws = w
            break

    if ws is None:
        st.write("No data for this date.")
        return

    rows = ws.get_all_values()
    if not rows or len(rows) <= 1:
        st.write("No rows submitted for this date.")
        return

    header = rows[0]
    data_rows = rows[1:]
    df = pd.DataFrame(data_rows, columns=header)

    st.markdown(f"Showing data for **{selected}**:")
    st.markdown('<div class="no-select-table">', unsafe_allow_html=True)
    st.dataframe(df, use_container_width=True)
    st.markdown('</div>', unsafe_allow_html=True)


# ---------------------- NEW ENTRY TAB ----------------------

def new_entry_tab():
    st.subheader("New Data Entry (Write-Only)")

    st.write(
        "Enter rows below. After you click **Submit**, the table is cleared. "
        "Previous entries can be viewed only in the **Previous Entries** tab."
    )

    # Hide toolbar for the editor too
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

    if "input_df" not in st.session_state:
        st.session_state["input_df"] = pd.DataFrame(
            [["" for _ in COLUMNS] for _ in range(DEFAULT_ROWS)],
            columns=COLUMNS,
        )

    edited = st.data_editor(
        st.session_state["input_df"],
        num_rows="dynamic",
        hide_index=True,
        use_container_width=True,
        key="data_editor",
    )

    col1, col2 = st.columns(2)

    with col1:
        submit = st.button("Submit to Google Sheet", type="primary")

    with col2:
        clear = st.button("Clear Table")

    if clear:
        # Reset and rerun
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
                # Hard reset: remove input_df and rerun
                if "input_df" in st.session_state:
                    del st.session_state["input_df"]
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

    tab1, tab2 = st.tabs(["New Entry", "Previous Entries"])

    with tab1:
        new_entry_tab()

    with tab2:
        history_tab()


if __name__ == "__main__":
    main()
