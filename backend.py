# backend.py — GPT Evaluator + Role Extractor

import json
from constants import AZURE_CONFIG, MODEL_CONFIG, WEIGHTS, STRICT_GPT_PROMPT
from openai import AzureOpenAI
from utils import chunk_text
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

# GPT client
client = AzureOpenAI(
    api_key=AZURE_CONFIG["openai_key"],
    api_version=AZURE_CONFIG["api_version"],
    azure_endpoint=AZURE_CONFIG["azure_endpoint"]
)

# ========== JD Role Extractor ==========
def extract_role_from_jd(jd_text: str) -> str:
    try:
        prompt = f"""
You are an expert recruiter AI. Extract the most appropriate job title from the following job description.
- If no clear title is mentioned, infer the best-fit role based on the responsibilities and skills.
- Return only the concise role title like "Data Analyst", "Frontend Developer", "Embedded Software Engineer", etc.
- If you cannot determine a role, return "N/A".

Job Description:
\"\"\"
{jd_text[:4000]}
\"\"\"
"""

        response = client.chat.completions.create(
            model=MODEL_CONFIG["fast_gpt_model"],
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=20,
        )
        role = response.choices[0].message.content.strip()
        return role if 2 <= len(role.split()) <= 6 else "N/A"
    except Exception:
        return "N/A"

# ========== Async Resume Evaluator ==========
async def get_resume_analysis_async(
    jd: str,
    resume_text: str,
    contact: dict,
    role: str,
    domain: str,
    skills: str,
    experience_range: str,
    jd_similarity: float,
    resume_file: str
) -> dict:
    try:
        chunks = chunk_text(resume_text)
        combined_text = "\n\n".join(chunks[:3])  # ~3000 tokens

        messages = [
            {"role": "system", "content": STRICT_GPT_PROMPT.strip()},
            {"role": "user", "content": f"""
JD: {jd}

ROLE: {role}
DOMAIN: {domain}
REQUIRED SKILLS: {skills}
EXPERIENCE RANGE: {experience_range}

RESUME:
{combined_text}
"""}
        ]

        response = client.chat.completions.create(
            model=MODEL_CONFIG["deep_gpt_model"],
            messages=messages,
            temperature=0.2,
            max_tokens=1200
        )

        raw = response.choices[0].message.content
        return parse_gpt_response(raw, contact, role, jd_similarity, resume_text, resume_file)

    except Exception as e:
        return failed_json(contact, role, jd_similarity, resume_text, resume_file, reason=str(e))

# ========== GPT Response Parser ==========
def parse_gpt_response(raw_json, contact, role, jd_similarity, resume_text, resume_file):
    try:
        parsed = json.loads(raw_json)
    except:
        return failed_json(contact, role, jd_similarity, resume_text, resume_file, reason="❌ GPT parsing failed")

    def get(k, fallback):
        return parsed.get(k, fallback)

    skills = get("skills_match", 0)
    domain = get("domain_match", 0)
    exp = get("experience_match", 0)

    final_score = (
        skills * WEIGHTS["skills_match"] +
        domain * WEIGHTS["domain_match"] +
        exp * WEIGHTS["experience_match"] +
        jd_similarity * WEIGHTS["jd_similarity"]
    )

    score_rounded = round(final_score, 2)

    # Reject if below threshold score
    verdict = get("verdict", "review")
    rejection_reasons = get("reasons_if_rejected", [])
    if score_rounded < 50:
        verdict = "reject"
        rejection_reasons.append(f"Score below threshold ({score_rounded} < 50)")

    # Final fallback contact name if GPT didn't extract
    extracted_name = get("name", "N/A") or contact.get("name", "N/A")
    final_name = extracted_name if extracted_name != "N/A" else contact.get("name", "N/A")

    return {
        "name": final_name or "N/A",
        "email": contact.get("email", "N/A"),
        "phone": contact.get("phone", "N/A"),
        "jd_role": get("jd_role", role),
        "skills_match": skills,
        "domain_match": domain,
        "experience_match": exp,
        "jd_similarity": jd_similarity,
        "score": score_rounded,
        "fitment": get("fitment", "N/A"),
        "summary_5_lines": get("summary_5_lines", "N/A"),
        "red_flags": get("red_flags", []),
        "missing_gaps": get("missing_gaps", []),
        "fraud_detected": get("fraud_detected", False),
        "reasons_if_rejected": rejection_reasons,
        "recommendation": get("recommendation", "N/A"),
        "highlights": get("highlights", []),
        "verdict": verdict,
        "resume_text": resume_text,
        "resume_file": resume_file
    }

# ========== Fallback on GPT Failure ==========
def failed_json(contact, role, jd_similarity, resume_text, resume_file, reason="GPT error"):
    return {
        "name": contact.get("name", "N/A"),
        "email": contact.get("email", "N/A"),
        "phone": contact.get("phone", "N/A"),
        "jd_role": role,
        "skills_match": 0,
        "domain_match": 0,
        "experience_match": 0,
        "jd_similarity": jd_similarity,
        "score": 0,
        "fitment": reason,
        "summary_5_lines": "N/A",
        "red_flags": ["GPT failure"],
        "missing_gaps": ["N/A"],
        "fraud_detected": True,
        "reasons_if_rejected": ["Parsing failed"],
        "recommendation": "N/A",
        "highlights": [],
        "verdict": "reject",
        "resume_text": resume_text,
        "resume_file": resume_file
    }
