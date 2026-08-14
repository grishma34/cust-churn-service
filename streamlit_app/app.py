"""Streamlit front door (REQ-0016): a form for non-technical users to test
churn predictions against the deployed API.

This app is deliberately a THIN HTTP CLIENT: it holds no model, no AWS
credentials, and imports nothing from src/ — the Lambda is the only inference
path in existence, so this UI can never disagree with production
(docs/ARCHITECTURE.md). The field spec below is a literal copy of the API
schema, pinned to src/shared/schema.py by tests/unit/streamlit_app/ — if they
drift, the build fails.
"""

import os

import requests
import streamlit as st

DEFAULT_API_URL = "https://zbvlinpfnupzjrsrxfhjcchp440rcttr.lambda-url.ap-southeast-2.on.aws"

# --- field spec: MUST match src/shared/schema.py (test-enforced) -------------

NUMERIC_FIELDS = ("tenure", "MonthlyCharges", "TotalCharges")

CATEGORICAL_DOMAINS = {
    "gender": ("Female", "Male"),
    "SeniorCitizen": (0, 1),
    "Partner": ("No", "Yes"),
    "Dependents": ("No", "Yes"),
    "PhoneService": ("No", "Yes"),
    "MultipleLines": ("No", "No phone service", "Yes"),
    "InternetService": ("DSL", "Fiber optic", "No"),
    "OnlineSecurity": ("No", "No internet service", "Yes"),
    "OnlineBackup": ("No", "No internet service", "Yes"),
    "DeviceProtection": ("No", "No internet service", "Yes"),
    "TechSupport": ("No", "No internet service", "Yes"),
    "StreamingTV": ("No", "No internet service", "Yes"),
    "StreamingMovies": ("No", "No internet service", "Yes"),
    "Contract": ("Month-to-month", "One year", "Two year"),
    "PaperlessBilling": ("No", "Yes"),
    "PaymentMethod": (
        "Bank transfer (automatic)",
        "Credit card (automatic)",
        "Electronic check",
        "Mailed check",
    ),
}

# -----------------------------------------------------------------------------


def api_url() -> str:
    try:
        if "api_url" in st.secrets:
            return st.secrets["api_url"].rstrip("/")
    except FileNotFoundError:
        pass
    return os.environ.get("API_URL", DEFAULT_API_URL).rstrip("/")


@st.cache_data(ttl=300)
def model_info(base_url: str) -> dict | None:
    try:
        response = requests.get(f"{base_url}/model", timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.RequestException:
        return None


st.set_page_config(page_title="Churn Predictor", page_icon="📉")
st.title("📉 Customer Churn Predictor")

base_url = api_url()
info = model_info(base_url)
if info:
    st.caption(
        f"Model `{info['model_version']}` · decision threshold "
        f"{info['threshold']:.3f} (cost-based: FP ${info['costs']['false_positive']:.0f} / "
        f"FN ${info['costs']['false_negative']:.0f}) · "
        f"test ROC AUC {info['metrics']['test']['roc_auc']:.3f}"
    )
else:
    st.warning("Could not reach the model API — predictions may fail.")

with st.form("customer"):
    st.subheader("Customer profile")

    demo, services, billing = st.tabs(["Demographics", "Services", "Billing"])

    with demo:
        gender = st.selectbox("Gender", CATEGORICAL_DOMAINS["gender"])
        senior = st.selectbox("Senior citizen", ("No", "Yes"))
        partner = st.selectbox("Has a partner", CATEGORICAL_DOMAINS["Partner"])
        dependents = st.selectbox("Has dependents", CATEGORICAL_DOMAINS["Dependents"])

    with services:
        phone = st.selectbox("Phone service", CATEGORICAL_DOMAINS["PhoneService"])
        multiple = st.selectbox("Multiple lines", CATEGORICAL_DOMAINS["MultipleLines"])
        internet = st.selectbox("Internet service", CATEGORICAL_DOMAINS["InternetService"])
        col1, col2 = st.columns(2)
        with col1:
            security = st.selectbox("Online security", CATEGORICAL_DOMAINS["OnlineSecurity"])
            backup = st.selectbox("Online backup", CATEGORICAL_DOMAINS["OnlineBackup"])
            protection = st.selectbox("Device protection", CATEGORICAL_DOMAINS["DeviceProtection"])
        with col2:
            support = st.selectbox("Tech support", CATEGORICAL_DOMAINS["TechSupport"])
            tv = st.selectbox("Streaming TV", CATEGORICAL_DOMAINS["StreamingTV"])
            movies = st.selectbox("Streaming movies", CATEGORICAL_DOMAINS["StreamingMovies"])

    with billing:
        contract = st.selectbox("Contract", CATEGORICAL_DOMAINS["Contract"])
        paperless = st.selectbox("Paperless billing", CATEGORICAL_DOMAINS["PaperlessBilling"])
        payment = st.selectbox("Payment method", CATEGORICAL_DOMAINS["PaymentMethod"])
        tenure = st.number_input("Tenure (months)", min_value=0, max_value=120, value=12)
        monthly = st.number_input(
            "Monthly charges ($)", min_value=0.0, max_value=500.0, value=70.0, step=5.0
        )
        new_customer = st.checkbox("New customer — no total charges billed yet", value=False)
        total = st.number_input(
            "Total charges ($)",
            min_value=0.0,
            max_value=20000.0,
            value=840.0,
            step=50.0,
            disabled=new_customer,
        )

    submitted = st.form_submit_button("Predict churn risk", use_container_width=True)

if submitted:
    payload = {
        "gender": gender,
        "SeniorCitizen": 1 if senior == "Yes" else 0,
        "Partner": partner,
        "Dependents": dependents,
        "PhoneService": phone,
        "MultipleLines": multiple,
        "InternetService": internet,
        "OnlineSecurity": security,
        "OnlineBackup": backup,
        "DeviceProtection": protection,
        "TechSupport": support,
        "StreamingTV": tv,
        "StreamingMovies": movies,
        "Contract": contract,
        "PaperlessBilling": paperless,
        "PaymentMethod": payment,
        "tenure": int(tenure),
        "MonthlyCharges": float(monthly),
        "TotalCharges": None if new_customer else float(total),
    }
    with st.spinner("Asking the model… (first request after idle can take ~10 s)"):
        try:
            response = requests.post(f"{base_url}/predict", json=payload, timeout=60)
        except requests.RequestException as exc:
            st.error(f"Could not reach the API: {exc}")
            st.stop()

    if response.status_code == 200:
        result = response.json()
        probability = result["churn_probability"]
        st.metric("Churn probability", f"{probability:.1%}")
        st.progress(min(max(probability, 0.0), 1.0))
        if result["churn_predicted"]:
            st.error(
                f"**Likely to churn** — probability {probability:.1%} is at or above "
                f"the {result['threshold']:.1%} action threshold. "
                "A retention offer is worth it: a missed churner costs ~9× a wasted offer."
            )
        else:
            st.success(
                f"**Likely to stay** — probability {probability:.1%} is below "
                f"the {result['threshold']:.1%} action threshold."
            )
        st.caption(
            f"Prediction `{result['prediction_id']}` by model `{result['model_version']}` "
            f"at {result['timestamp']} — fully traceable in the audit log."
        )
        with st.expander("Raw API response"):
            st.json(result)
    elif response.status_code == 400:
        details = response.json().get("error", {}).get("details", [])
        st.error("The API rejected the input:")
        for detail in details:
            st.write(f"- **{detail['field']}**: {detail['issue']}")
    else:
        st.error(f"API error {response.status_code}: {response.text[:500]}")
