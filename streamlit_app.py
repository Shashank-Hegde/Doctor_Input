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

# Set page config once at top-level
st.set_page_config(page_title="Doctor Input Portal", layout="wide")


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


def build_mapping_template(df_ref: pd.DataFrame) -> pd.DataFrame:
    """
    Build the initial template used in the Streamlit editor:

    - Row 0: same as Excel (template row).
    - Col 0 and 1 (first two columns): same as Excel.
    - All other cells (row >= 1, col >= 2) are blank, ready for user input.
    """
    template = df_ref.copy()
    if template.shape[0] > 1 and template.shape[1] > 2:
        template.iloc[1:, 2:] = ""
    return template


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

    Behavior:
    - First 2 columns and first row *come from Excel*.
    - Only cells with row >= 1 and col >= 2 are editable.
    - Edits persist in the UI (widget state) until the user clicks Submit.
    - On Submit:
        * Save full grid to mapping_YYYY-MM-DD (with row1 + first 2 cols restored from Excel).
        * Reset the editor to a fresh template (clears editable cells only).
    """

    st.subheader("Specialty Mapping – Scenario Grid")

    df_ref = load_reference_sheet()
    if df_ref is None:
        st.info("Reference sheet not available or could not be loaded.")
        return

    df_ref = df_ref.fillna("").astype(str)
    num_rows, num_cols = df_ref.shape

    if num_cols < 3:
        st.error("Specialty Mapping.xlsx must have at least 3 columns.")
        return

    st.markdown(
        """
        - **Row 1** and **first two columns** come from the Excel template.  
        - All other cells are editable and will stay as you type until you press **Submit Specialty Mapping**.  
        - On submit, data is sent to Google Sheets (`mapping_YYYY-MM-DD`) and the editable cells are cleared.
        """
    )

    # CSS to enable horizontal scrolling and not clip wide columns
    st.markdown(
        """
        <style>
        div[data-testid="stDataFrameResizable"] {
            overflow-x: auto;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # If we just submitted previously, clear the widget state
    if st.session_state.get("mapping_clear_after_submit", False):
        if "mapping_editor" in st.session_state:
            del st.session_state["mapping_editor"]
        st.session_state["mapping_clear_after_submit"] = False

    # Build the template (row1 + first 2 cols fixed, other cells blank)
    df_template = build_mapping_template(df_ref)

    # Column configuration:
    # - First 2 columns: disabled (non-editable).
    # - Last column: wide for notes.
    column_config = {}
    for i, col in enumerate(df_ref.columns):
        if i < 2:
            column_config[col] = st.column_config.TextColumn(disabled=True)
        elif i == num_cols - 1:
            column_config[col] = st.column_config.TextColumn(width="large")
        else:
            column_config[col] = st.column_config.TextColumn()

    # Single unified data editor.
    # IMPORTANT:
    # - We pass df_template as the "initial" data.
    # - Streamlit keeps user edits in the widget's internal state keyed by "mapping_editor".
    # - We do NOT overwrite it from session_state each rerun, so data doesn't vanish.
    edited = st.data_editor(
        df_template,
        num_rows="fixed",
        hide_index=False,
        use_container_width=False,  # allow horizontal scroll if table is wide
        column_config=column_config,
        key="mapping_editor",
    )

    # Submit button
    if st.button("Submit Specialty Mapping", type="primary"):
        try:
            ws = get_mapping_sheet_for_today()

            full_df = edited.copy()
            full_df = full_df.fillna("").astype(str)

            # Enforce template parts on SAVE:
            # 1) First row from Excel
            full_df.iloc[0, :] = df_ref.iloc[0, :]

            # 2) First 2 columns from Excel
            full_df.iloc[:, 0:2] = df_ref.iloc[:, 0:2]

            # Prepare header + values as strings
            header = ["" if (h is None or str(h) == "nan") else str(h) for h in full_df.columns]
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

            # Write to Google Sheets (values first, then range_name)
            ws.clear()
            ws.update(values=[header] + clean_values, range_name="A1")

            st.success(
                "Specialty Mapping saved to Google Sheets "
                f"(sheet: '{ws.title}')."
            )

            # Reset editor on next run: clear widget state,
            # then df_template will be used again (blank editable cells).
            st.session_state["mapping_clear_after_submit"] = True
            st.rerun()

        except Exception as e:
            st.error(f"Error saving mapping to Google Sheets: {e}")


# ---------------------- MAIN ----------------------

def main():
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
