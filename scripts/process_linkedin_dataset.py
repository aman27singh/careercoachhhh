"""
Process LinkedIn Job Postings dataset to extract skill demand frequency.

Usage:
    python scripts/process_linkedin_dataset.py <input_csv> [output_json]

Example:
    python scripts/process_linkedin_dataset.py data/jobs.csv
"""

import argparse
import json
from collections import Counter
from pathlib import Path

import pandas as pd

ROLE_MAPPINGS = {
    "Backend Developer": [
        "backend engineer",
        "backend developer",
        "full-stack developer",
        "python developer",
        "api developer",
        "server-side developer",
        "systems engineer",
    ],
    "Machine Learning Engineer": [
        "machine learning engineer",
        "ml engineer",
        "data scientist",
        "ml researcher",
        "ai engineer",
        "deep learning engineer",
    ],
    "Frontend Developer": [
        "frontend engineer",
        "frontend developer",
        "ui engineer",
        "react developer",
        "web developer",
        "javascript developer",
        "full-stack developer",
    ],
    "Data Analyst": [
        "data analyst",
        "data engineer",
        "analytics engineer",
        "bi analyst",
        "business analyst",
        "sql analyst",
    ],
}

SKILL_NORMALIZATIONS = {
    "python3": "python",
    "js": "javascript",
    "ts": "typescript",
    "sql server": "sql",
    "nosql": "mongodb",
    "ml": "machine learning",
    "ai": "artificial intelligence",
    "devops": "devops",
    "k8s": "kubernetes",
    "gs": "google suite",
}


def normalize_job_title(job_title: str) -> str | None:
    if not job_title:
        return None
    normalized = job_title.lower().strip()
    for role, keywords in ROLE_MAPPINGS.items():
        for keyword in keywords:
            if keyword in normalized:
                return role
    return None


def normalize_skill(skill: str) -> str | None:
    if not skill:
        return None
    normalized = skill.lower().strip()
    return SKILL_NORMALIZATIONS.get(normalized, normalized)


def extract_skills_from_text(skills_text: str) -> list[str]:
    if not skills_text or not isinstance(skills_text, str):
        return []
    skills = [s.strip() for s in skills_text.split(",")]
    skills = [normalize_skill(s) for s in skills if s]
    return [s for s in skills if s]


def process_dataset(input_csv: str, output_json: str) -> None:
    print(f"Reading dataset from {input_csv}...")
    df = pd.read_csv(input_csv)

    title_col = None
    skills_col = None

    for col in df.columns:
        col_lower = col.lower()
        if "title" in col_lower and title_col is None:
            title_col = col
        if "skill" in col_lower and skills_col is None:
            skills_col = col

    if not title_col or not skills_col:
        available = list(df.columns)
        raise ValueError(
            f"Could not find title and skills columns. "
            f"Available columns: {available}"
        )

    print(f"Using columns: '{title_col}' for job titles, '{skills_col}' for skills")

    role_skills = {
        "Backend Developer": Counter(),
        "Machine Learning Engineer": Counter(),
        "Frontend Developer": Counter(),
        "Data Analyst": Counter(),
    }

    role_counts = {role: 0 for role in role_skills.keys()}

    print("Processing entries...")
    for idx, row in df.iterrows():
        job_title = row.get(title_col)
        skills_text = row.get(skills_col)

        role = normalize_job_title(job_title)
        if not role:
            continue

        role_counts[role] += 1
        skills = extract_skills_from_text(skills_text)

        for skill in set(skills):
            role_skills[role][skill] += 1

    print("\nComputing frequencies...")
    output_data = {}

    for role, skills_counter in role_skills.items():
        count = role_counts[role]
        if count == 0:
            print(f"  {role}: 0 postings, skipping")
            continue

        frequencies = {
            skill: round(freq / count, 2) for skill, freq in skills_counter.items()
        }

        top_25 = dict(sorted(frequencies.items(), key=lambda x: x[1], reverse=True)[:25])

        output_data[role] = top_25
        print(
            f"  {role}: {count} postings, {len(top_25)} unique skills, "
            f"top skill: {list(top_25.keys())[0] if top_25 else 'none'}"
        )

    output_path = Path(output_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w") as f:
        json.dump(output_data, f, indent=2)

    print(f"\nOutput saved to {output_json}")


def main():
    parser = argparse.ArgumentParser(
        description="Process LinkedIn Job Postings dataset."
    )
    parser.add_argument("input_csv", help="Path to input CSV file")
    parser.add_argument(
        "--output",
        "-o",
        default="app/data/market_skills.json",
        help="Path to output JSON file (default: app/data/market_skills.json)",
    )

    args = parser.parse_args()

    try:
        process_dataset(args.input_csv, args.output)
    except FileNotFoundError as e:
        print(f"Error: {e}")
        exit(1)
    except ValueError as e:
        print(f"Error: {e}")
        exit(1)


if __name__ == "__main__":
    main()
