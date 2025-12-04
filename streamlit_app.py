import streamlit as st
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo

import gspread
from google.oauth2.service_account import Credentials


# ---------------------- CONFIG ----------------------

# Users with roles
# Change passwords before using!
VALID_USERS = {
    "engineer": {"password": "engineer123", "role": "engineer"},
    "admin": {"password": "admin123", "role": "admin"},
}

# Data entry columns (edit as needed)
COLUMNS = ["col1", "col2", "col3", "col4"]

# Blank rows shown to engineer
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
                # ignore sheets with wrong format
                continue

    # Sort by date descending (newest first)
    date_sheets.sort(key=lambda x: x[0], reverse=True)
    return date_sheets


# ---------------------- LOGIN PAGE ----------------------

def login_page():
    st.title("Secure Login")

    username = st.text_input("Username")
    password = st.text_input("Password", type="password")
    login_btn = st.button("Login")

    if login_btn:
        user = VALID_USERS.get(username)
        if user and user["password"] == password:
            st.session_state["logged_in"] = True
            st.session_state["user_role"] = user["role"]
            st.rerun()
        else:
            st.error("Invalid username or password")


# ---------------------- ENTRY PAGE ----------------------

def data_entry_section():
    st.subheader("New Data Entry (Write-Only)")

    st.write("Enter rows below. Once submitted, this page is cleared and you cannot copy previous inputs from here.")

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
    )

    col1, col2 = st.columns(2)

    with col1:
        submit = st.button("Submit to Google Sheet", type="primary")

    with col2:
        clear = st.button("Clear Table")

    if clear:
        st.session_state["input_df"] = pd.DataFrame(
            [["" for _ in COLUMNS] for _ in range(DEFAULT_ROWS)], columns=COLUMNS
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

                # Clear after submit so they cannot copy submitted content
                st.session_state["input_df"] = pd.DataFrame(
                    [["" for _ in COLUMNS] for _ in range(DEFAULT_ROWS)],
                    columns=COLUMNS,
                )
                st.rerun()
        except Exception as e:
            st.error(f"Error: {e}")


# ---------------------- VIEW PAGE (ADMIN) ----------------------

def view_history_section():
    st.subheader("View Submitted Data (Read-only)")

    st.info(
        "Below is a read-only view of past submissions by date. "
        "Copying is limited in the browser UI, but cannot be completely prevented."
    )

    # CSS to reduce text selection / copying
    st.markdown(
        """
        <style>
        .no-select * {
            -webkit-user-select: none;
            -moz-user-select: none;
            -ms-user-select: none;
            user-select: none;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    date_sheets = get_date_sheets()
    if not date_sheets:
        st.write("No data sheets found yet.")
        return

    labels = [ds[1] for ds in date_sheets]  # date_str
    tabs = st.tabs(labels)

    for tab, (_, date_str, ws) in zip(tabs, date_sheets):
        with tab:
            st.write(f"Data for **{date_str}**:")

            rows = ws.get_all_values()
            if not rows:
                st.write("No data.")
                continue

            header = rows[0]
            data_rows = rows[1:]

            if not data_rows:
                st.write("No data rows.")
                continue

            df = pd.DataFrame(data_rows, columns=header)

            # Wrap in a div that disables text selection
            st.markdown('<div class="no-select">', unsafe_allow_html=True)
            st.dataframe(df, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)


# ---------------------- MAIN APP ----------------------

def main():
    st.set_page_config(page_title="Secure Doctor Input", layout="wide")

    if "logged_in" not in st.session_state:
        st.session_state["logged_in"] = False
        st.session_state["user_role"] = None

    if not st.session_state["logged_in"]:
        login_page()
        return

    role = st.session_state.get("user_role", "engineer")

    st.sidebar.write(f"Logged in as: **{role}**")
    if st.sidebar.button("Logout"):
        st.session_state.clear()
        st.rerun()

    st.title("Doctor Input Portal")

    # Data entry is available to everyone
    data_entry_section()

    # History view only for admins
    if role == "admin":
        st.markdown("---")
        view_history_section()


if __name__ == "__main__":
    main()
