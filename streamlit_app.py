import streamlit as st
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

# ---------------------- CONFIG ----------------------

# Logins:
# - doctor/password123 => New Entry only
# - admin/doctor       => New Entry + Previous Entries + Mapping editor
VALID_USERS = {
    "doctor": {"password": "password123", "role": "doctor"},
    "admin": {"password": "doctor", "role": "admin"},
}

# Change these to your real column names for NEW ENTRY table
COLUMNS = ["col1", "col2", "col3", "col4"]

DEFAULT_ROWS = 10
TIMEZONE = "Asia/Kolkata"

# Excel reference file (must live next to this .py file in the repo)
BASE_DIR = Path(__file__).parent
EXCEL_FILE = BASE_DIR / "Specialty Mapping.xlsx"


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
    return len(df_clean)


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


def get_mapping_sheet():
    """
    Get or create a dedicated worksheet to store the edited Specialty Mapping grid.
    This is separate from the daily data_YYYY-MM-DD sheets.
    """
    sh = get_spreadsheet()
    sheet_name = "specialty_mapping"
    try:
        ws = sh.worksheet(sheet_name)
    except gspread.WorksheetNotFound:
        # Create with some generous size; we'll overwrite contents on every save.
        ws = sh.add_worksheet(title=sheet_name, rows="2000", cols="50")
    return ws


# ---------------------- SPECIALTY MAPPING (EXCEL) ----------------------

@st.cache_data
def load_reference_sheet():
    """
    Load Specialty Mapping.xlsx and cache it.
    This is the template: first 2 cols + first row are 'frozen'.
    """
    try:
        df = pd.read_excel(EXCEL_FILE)
        if df is None or df.empty:
            return None
        return df
    except Exception as e:
        st.error(f"Failed to load Excel file '{EXCEL_FILE.name}': {e}")
        return None


def mapping_editor_section(role: str):
    """
    Homepage section: show & edit Specialty Mapping.xlsx.
    - First 2 columns and first row are constant.
    - Adjacent cells are editable.
    - On submit, entire grid is written to Google Sheets (specialty_mapping sheet).
    """
    st.subheader("Specialty Mapping – Reference & Input")

    df_ref = load_reference_sheet()
    if df_ref is None:
        st.info("Reference sheet not available or could not be loaded.")
        return

    # Define 'frozen' structure
    frozen_cols = list(df_ref.columns[:2])  # first 2 columns
    frozen_row_idx = df_ref.index[0]        # first row

    st.markdown(
        """
        - **First two columns** and **first row** are fixed from the reference Excel.  
        - You can fill or edit the **adjacent cells** (other columns / lower rows).  
        - Click **Submit Specialty Mapping** to save the entire grid to Google Sheets.
        """
    )

    # Initialize session state for editable mapping df
    if "mapping_df" not in st.session_state:
        # Start from the excel template
        st.session_state["mapping_df"] = df_ref.copy()

    current_df = st.session_state["mapping_df"]

    # Column config: lock first two columns in the UI
    column_config = {}
    for c in current_df.columns:
        if c in frozen_cols:
            column_config[c] = st.column_config.Column(disabled=True)
        else:
            column_config[c] = st.column_config.Column()

    edited = st.data_editor(
        current_df,
        num_rows="fixed",           # keep same structure as Excel
        hide_index=True,
        use_container_width=True,
        column_config=column_config,
        key="mapping_editor",
    )

    # Enforce frozen values: restore first two columns and first row
    # from the original reference df so they truly stay constant.
    edited.loc[:, frozen_cols] = df_ref.loc[:, frozen_cols]
    edited.loc[frozen_row_idx, :] = df_ref.loc[frozen_row_idx, :]

    # Update session state
    st.session_state["mapping_df"] = edited

    # Submit button (you might choose to restrict to admin only)
    if st.button("Submit Specialty Mapping", type="primary"):
        try:
            ws = get_mapping_sheet()

            # Clear existing contents
            ws.clear()

            # Prepare data: header row + all values
            header = list(edited.columns)
            values = edited.values.tolist()
            ws.update("A1", [header] + values)

            st.success("Specialty Mapping saved to Google Sheets (sheet: 'specialty_mapping').")
        except Exception as e:
            st.error(f"Error saving mapping to Google Sheets: {e}")


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
    st.subheader("Previous Entries")

    # Make table hard to copy from (not bullet-proof)
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
    st.subheader("New Data Entry")

    st.write(
        "Enter rows below. After you click **Submit**, the table is cleared. "
    )

    # Hide widget toolbar (CSV/download)
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

    # Use a dynamic key to reset the editor on demand
    if "editor_key" not in st.session_state:
        st.session_state["editor_key"] = "editor_1"

    editor_key = st.session_state["editor_key"]

    # Always start with blank df for a new key; for an existing key,
    # Streamlit will keep the internal value as the user edits.
    df_default = blank_df()

    edited = st.data_editor(
        df_default,
        num_rows="dynamic",
        hide_index=True,
        use_container_width=True,
        key=editor_key,
    )

    col1, col2 = st.columns(2)
    with col1:
        submit = st.button("Submit to Google Sheet", type="primary")
    with col2:
        clear = st.button("Clear Table")

    if clear:
        # Change the key so the widget is recreated with a fresh blank table
        st.session_state["editor_key"] = f"editor_reset_{datetime.now().timestamp()}"
        st.rerun()

    if submit:
        try:
            ws = get_today_sheet()
            saved_rows = append_rows(ws, edited)
            if saved_rows == 0:
                st.warning("No non-empty rows to save.")
            else:
                st.success(f"Saved {saved_rows} rows to today's sheet.")
                # Change key to reset editor to blank
                st.session_state["editor_key"] = f"editor_reset_{datetime.now().timestamp()}"
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

    # ---- HOMEPAGE: Specialty Mapping editor (for both roles; you can restrict to admin if you want) ----
    mapping_editor_section(role)

    st.markdown("---")

    # ---- Tabs for daily data entry / history ----
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
