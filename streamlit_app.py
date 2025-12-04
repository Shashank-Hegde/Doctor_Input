import streamlit as st
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo

import gspread
from google.oauth2.service_account import Credentials


# ---------------------- CONFIG ----------------------

VALID_USERS = {
    "doctor": {"password": "password123", "role": "doctor"},
    "admin": {"password": "admin123", "role": "admin"},
}

# TODO: put your real columns here
COLUMNS = ["col1", "col2", "col3", "col4"]

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
    df_clean = df.dropna(how="all")
    if df_clean.empty:
        return 0
    for row in df_clean.values.tolist():
        ws.append_row(row, value_input_option="USER_ENTERED")
    return len(df_clean)


def get_date_sheets():
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


# ---------------------- LOGIN ----------------------

def login_page():
    st.title("Secure Login")
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")
    if st.button("Login"):
        user = VALID_USERS.get(username)
        if user and user["password"] == password:
            st.session_state["logged_in"] = True
            st.session_state["user_role"] = user["role"]
            st.rerun()
        else:
            st.error("Invalid username or password")


# ---------------------- PREVIOUS ENTRIES (ADMIN ONLY) ----------------------

def history_tab():
    st.subheader("Previous Entries (Read-only)")

    # Make table as hard as possible to copy from (still not bullet-proof)
    st.markdown(
        """
        <style>
        .no-select-table, .no-select-table * {
            -webkit-user-select: none !important;
            -moz-user-select: none !important;
            -ms-user-select: none !important;
            user-select: none !important;
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

    ws = next((w for d, w in date_sheets if d == selected), None)
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

    html_table = df.to_html(index=False, escape=True)
    st.markdown(f'<div class="no-select-table">{html_table}</div>', unsafe_allow_html=True)
    st.caption("This view is read-only; text selection is disabled in the UI.")


# ---------------------- NEW ENTRY TAB ----------------------

def blank_df():
    return pd.DataFrame(
        [["" for _ in COLUMNS] for _ in range(DEFAULT_ROWS)],
        columns=COLUMNS,
    )


def new_entry_tab():
    st.subheader("New Data Entry (Write-Only)")

    st.write(
        "Enter rows below. After you click **Submit**, the table is cleared. "
        "Previous entries are only visible to admin."
    )

    # Hide toolbar (CSV/download) on the editor
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

    # Let the editor manage its own state via its key.
    if "editor_widget" not in st.session_state:
        st.session_state["editor_widget"] = blank_df()

    edited = st.data_editor(
        st.session_state["editor_widget"],
        num_rows="dynamic",
        hide_index=True,
        use_container_width=True,
        key="editor_widget",  # widget state lives here
    )
    # No manual assignment back; Streamlit already stores it in session_state["editor_widget"]

    col1, col2 = st.columns(2)
    with col1:
        submit = st.button("Submit to Google Sheet", type="primary")
    with col2:
        clear = st.button("Clear Table")

    if clear:
        st.session_state["editor_widget"] = blank_df()
        st.rerun()

    if submit:
        try:
            ws = get_today_sheet()
            df_to_save = st.session_state["editor_widget"]
            saved_rows = append_rows(ws, df_to_save)
            if saved_rows == 0:
                st.warning("No non-empty rows to save.")
            else:
                st.success(f"Saved {saved_rows} rows to today's sheet.")
                # Reset editor after successful save
                st.session_state["editor_widget"] = blank_df()
                st.rerun()
        except Exception as e:
            st.error(f"Error: {e}")


# ---------------------- MAIN ----------------------

def main():
    st.set_page_config(page_title="Doctor Input Portal", layout="wide")

    if "logged_in" not in st.session_state:
        st.session_state["logged_in"] = False
        st.session_state["user_role"] = None

    if not st.session_state["logged_in"]:
        login_page()
        return

    role = st.session_state.get("user_role", "doctor")

    with st.sidebar:
        st.write(f"Logged in as: **{role}**")
        if st.button("Logout"):
            st.session_state.clear()
            st.rerun()

    st.title("Doctor Input Portal")

    if role == "admin":
        tab1, tab2 = st.tabs(["New Entry", "Previous Entries"])
        with tab1:
            new_entry_tab()
        with tab2:
            history_tab()
    else:
        (tab1,) = st.tabs(["New Entry"])
        with tab1:
            new_entry_tab()


if __name__ == "__main__":
    main()
