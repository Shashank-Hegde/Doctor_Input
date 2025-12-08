import streamlit as st
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo

import gspread
from google.oauth2.service_account import Credentials


# ---------------------- CONFIG ----------------------

# Logins:
# - doctor / password123 => New Entry + Mapping
# - admin  / doctor      => New Entry + Previous Entries + Mapping
VALID_USERS = {
    "doctor": {"password": "password123", "role": "doctor"},
    "admin": {"password": "doctor", "role": "admin"},
}

# Columns for the main data entry table
COLUMNS = ["col1", "col2", "col3", "col4"]

DEFAULT_ROWS = 10
TIMEZONE = "Asia/Kolkata"

# Excel file with the specialty mapping reference (must be in repo root)
EXCEL_FILE = "Specialty Mapping.xlsx"


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
    """Get or create today's worksheet for main data: data_YYYY-MM-DD."""
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

    df_clean = df_clean.fillna("").astype(str)
    rows = df_clean.values.tolist()
    for r in rows:
        ws.append_row(r, value_input_option="USER_ENTERED")
    return len(df_clean)


def get_date_sheets():
    """Return list of (date_str, worksheet) sorted by date descending for main data."""
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


def get_mapping_sheet_for_today():
    """
    Get or create today's worksheet for specialty mapping:
    mapping_YYYY-MM-DD
    All submissions on the same day go into this sheet.
    """
    sh = get_spreadsheet()
    now = datetime.now(ZoneInfo(TIMEZONE))
    sheet_name = f"mapping_{now.strftime('%Y-%m-%d')}"

    try:
        ws = sh.worksheet(sheet_name)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=sheet_name, rows="2000", cols="50")
    return ws


# ---------------------- EXCEL / SPECIALTY MAPPING HELPERS ----------------------

@st.cache_data
def load_reference_sheet():
    """
    Load Specialty Mapping.xlsx and cache it.
    Everything is treated as text; NaNs become empty strings.
    """
    try:
        df = pd.read_excel(EXCEL_FILE, dtype=str)
        if df is None or df.empty:
            return None
        df = df.fillna("")
        df.reset_index(drop=True, inplace=True)
        return df
    except Exception as e:
        st.error(f"Failed to load Excel file '{EXCEL_FILE}': {e}")
        return None


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
                st.session_state["editor_key"] = f"editor_reset_{datetime.now().timestamp()}"
                st.rerun()
        except Exception as e:
            st.error(f"Error: {e}")


# ---------------------- SPECIALTY MAPPING SECTION ----------------------

def mapping_editor_section(role: str):
    """
    Homepage section: show & edit Specialty Mapping.xlsx as ONE table.

    Behaviour:
    - First 2 columns are visually disabled (non-editable).
    - First row is logically frozen: any edits in row 0 are discarded on SAVE.
    - All other cells are editable and do NOT vanish while typing.
    - On submit:
        * Save today's mapping to Google Sheets (mapping_YYYY-MM-DD).
        * Reset the grid back to the original Excel contents.
    """

    st.subheader("Specialty Mapping – Scenario Grid")

    df_ref = load_reference_sheet()
    if df_ref is None:
        st.info("Reference sheet not available or could not be loaded.")
        return

    # Treat everything as text
    df_ref = df_ref.fillna("").astype(str)
    num_rows, num_cols = df_ref.shape

    if num_cols < 3:
        st.error("Specialty Mapping.xlsx must have at least 3 columns.")
        return

    st.markdown(
        """
        - **First two columns** are fixed from the Excel file (non-editable here).  
        - **First row** is logically frozen: any changes you make in row 1 will be **ignored on save**  
          and restored from the original Excel.  
        - All other cells are editable and changes are saved to a date-based sheet
          named `mapping_YYYY-MM-DD`.
        """
    )

    # --- Make horizontal scrolling easier and allow last column to be wider ---
    st.markdown(
        """
        <style>
        /* Ensure the data editor can scroll horizontally */
        div[data-testid="stDataFrameResizable"] {
            overflow-x: auto;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # Initialise persistent editable DF once
    if "mapping_df" not in st.session_state:
        st.session_state["mapping_df"] = df_ref.copy()

    if "mapping_editor_key" not in st.session_state:
        st.session_state["mapping_editor_key"] = "mapping_1"

    current_df = st.session_state["mapping_df"].copy()
    current_df = current_df.fillna("").astype(str)

    # Column configuration: first 2 columns disabled, last column wide
    column_config = {}
    for i, col in enumerate(df_ref.columns):
        if i < 2:
            # First 2 columns fixed / non-editable
            column_config[col] = st.column_config.TextColumn(disabled=True)
        elif i == len(df_ref.columns) - 1:
            # Last column (often "notes") wider for longer text
            column_config[col] = st.column_config.TextColumn(width="large")
        else:
            column_config[col] = st.column_config.TextColumn()

    # Single unified editor; we do NOT override cells here, so typing is smooth
    edited = st.data_editor(
        current_df,
        num_rows="fixed",
        hide_index=False,
        use_container_width=False,  # enables horizontal scroll if table is wider than container
        column_config=column_config,
        key=st.session_state["mapping_editor_key"],
    )

    edited = edited.fillna("").astype(str)
    # Store exactly what the user has typed; no freezing enforced here
    st.session_state["mapping_df"] = edited

    # --- Submit button ---
    if st.button("Submit Specialty Mapping", type="primary"):
        try:
            ws = get_mapping_sheet_for_today()

            full_df = st.session_state["mapping_df"].copy()
            full_df = full_df.fillna("").astype(str)

            # Enforce "frozen" parts ONLY at save time:
            # 1) First row from original Excel
            full_df.iloc[0, :] = df_ref.iloc[0, :]

            # 2) First 2 columns for all rows from original Excel
            full_df.iloc[:, 0:2] = df_ref.iloc[:, 0:2]

            # Prepare header + values as pure strings
            header = [
                "" if (h is None or str(h) == "nan") else str(h)
                for h in full_df.columns
            ]
            values = full_df.values.tolist()

            clean_values = []
            for row in values:
                clean_row = []
                for v in row:
                    if v is None:
                        clean_row.append("")
                    else:
                        v_str = str(v)
                        if v_str == "nan":
                            v_str = ""
                        clean_row.append(v_str)
                clean_values.append(clean_row)

            # Write to Google Sheets
            ws.clear()
            ws.update("A1", [header] + clean_values)

            st.success(
                "Specialty Mapping saved to Google Sheets "
                f"(sheet: '{ws.title}')."
            )

            # Reset editor back to original Excel content
            st.session_state["mapping_df"] = df_ref.copy()
            st.session_state["mapping_editor_key"] = f"mapping_{datetime.now().timestamp()}"
            st.rerun()

        except Exception as e:
            st.error(f"Error saving mapping to Google Sheets: {e}")



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

    # --- Specialty Mapping section on homepage ---
    mapping_editor_section(role)

    st.markdown("---")

    # --- Main data entry / history tabs ---
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
