"""Vorlagen für Zielrollen. Der Einrichtungsassistent bietet sie an; danach ist alles frei editierbar.

Eine Rolle ist ein Name plus Titel-Stichwörter (deutsch und englisch). Die Reihenfolge der Rollen ist die
Priorität: Treffer in der ersten Rolle bekommen den höchsten Score.
"""

from __future__ import annotations

from typing import Any

# Gilt für alle Vorlagen: Praktika, Abschlussarbeiten, Ausbildung, Nebenjobs.
COMMON_EXCLUDES = [
    # Juristische Stellen tragen manchmal Tech-Wörter im Titel (Echttest: „Legal Counsel … (Platform Workers)“)
    "counsel",
    "lawyer",
    "attorney",
    "paralegal",
    "jurist",
    "rechtsanwalt",
    "intern",
    "internship",
    "praktik",
    "werkstudent",
    "working student",
    "student",
    "thesis",
    "masterarbeit",
    "bachelorarbeit",
    "abschlussarbeit",
    "duales studium",
    "ausbildung",
    "aushilfe",
    "minijob",
]
# Führungsrollen – im Assistenten abwählbar.
LEADERSHIP_EXCLUDES = ["staff", "principal", "lead", "head of", "director", "teamleit", "manager"]

PRESETS: dict[str, dict[str, Any]] = {
    "cloud": {
        "label": {"de": "Cloud, DevOps & SRE", "en": "Cloud, DevOps & SRE"},
        "roles": [
            {
                "name": "SRE",
                "keywords": ["site reliability", "reliability", "sre", "observability", "monitoring"],
            },
            {
                "name": "Platform",
                "keywords": [
                    "platform",
                    "plattform",
                    "infrastructure",
                    "infra engineer",
                    "production engineer",
                ],
            },
            {
                "name": "DevOps",
                "keywords": [
                    "devops",
                    "dev ops",
                    "devsecops",
                    "mlops",
                    "gitops",
                    "release engineer",
                    "build engineer",
                    "automation engineer",
                    "test automation",
                    "testautomatisierung",
                ],
            },
            {"name": "Cloud", "keywords": ["cloud", "kubernetes", "k8s"]},
            {
                "name": "System",
                "keywords": [
                    "systems engineer",
                    "system engineer",
                    "systemingenieur",
                    "system-ingenieur",
                    "operations engineer",
                    "it operations",
                    "it-operations",
                    "technical operations",
                    "linux",
                    "unix",
                    "administrator",
                    "sysadmin",
                    "systemadministrat",
                    "it engineer",
                    "it-engineer",
                    "it specialist",
                    "it-spezialist",
                    "fachinformatiker",
                    "systemintegration",
                    "network engineer",
                    "netzwerk",
                    "infrastruktur",
                    "middleware",
                    "rechenzentrum",
                    "data center",
                    "datacenter",
                    "virtualisierung",
                    "virtualization",
                ],
            },
        ],
        "excludes": [
            "architect",
            "sales",
            "account",
            "marketing",
            "recruit",
            "data engineer",
            "data platform",
            "machine learning",
            "frontend",
            "android",
            "ios",
            "salesforce",
            "servicenow",
            "sap ",
            "crm",
            "erp",
            "product owner",
            "scrum",
            "designer",
        ],
        "skills": [
            "kubernetes",
            "terraform",
            "docker",
            "helm",
            "aws",
            "gcp",
            "azure",
            "linux",
            "python",
            "go",
            "bash",
            "prometheus",
            "grafana",
            "ci/cd",
            "ansible",
            "observability",
        ],
        "search_queries": [
            "devops",
            "site reliability",
            "platform engineer",
            "cloud engineer",
            "kubernetes",
            "infrastructure engineer",
            "linux",
        ],
    },
    "software": {
        "label": {"de": "Softwareentwicklung", "en": "Software engineering"},
        "roles": [
            {
                "name": "Backend",
                "keywords": [
                    "backend",
                    "back-end",
                    "java developer",
                    "python developer",
                    "golang",
                    "api engineer",
                ],
            },
            {"name": "Fullstack", "keywords": ["fullstack", "full-stack", "full stack"]},
            {
                "name": "Frontend",
                "keywords": [
                    "frontend",
                    "front-end",
                    "react",
                    "angular",
                    "vue",
                    "web developer",
                    "webentwickler",
                ],
            },
            {"name": "Mobile", "keywords": ["ios", "android", "mobile", "flutter", "react native"]},
            {
                "name": "Software",
                "keywords": [
                    "software engineer",
                    "software developer",
                    "softwareentwickler",
                    "softwareingenieur",
                    "entwickler",
                    "developer",
                    "programmierer",
                ],
            },
            {
                "name": "QA",
                "keywords": ["qa engineer", "quality assurance", "test engineer", "testautomatisierung"],
            },
        ],
        "excludes": ["sales", "account", "marketing", "recruit", "salesforce", "sap "],
        "skills": [
            "python",
            "java",
            "typescript",
            "javascript",
            "go",
            "kotlin",
            "react",
            "sql",
            "docker",
            "aws",
        ],
        "search_queries": [
            "backend engineer",
            "software engineer",
            "fullstack developer",
            "frontend developer",
        ],
    },
    "data": {
        "label": {"de": "Data & KI", "en": "Data & AI"},
        "roles": [
            {
                "name": "ML/AI",
                "keywords": ["machine learning", "ml engineer", "ai engineer", "ki ", "deep learning"],
            },
            {"name": "Data Science", "keywords": ["data scientist", "data science"]},
            {
                "name": "Data Engineering",
                "keywords": ["data engineer", "analytics engineer", "data platform", "etl"],
            },
            {
                "name": "Analytics",
                "keywords": ["data analyst", "bi ", "business intelligence", "datenanalyst"],
            },
        ],
        "excludes": ["sales", "account", "marketing", "recruit"],
        "skills": [
            "python",
            "sql",
            "spark",
            "airflow",
            "dbt",
            "pytorch",
            "tensorflow",
            "pandas",
            "aws",
            "snowflake",
        ],
        "search_queries": ["data engineer", "data scientist", "machine learning engineer", "data analyst"],
    },
    "it": {
        "label": {"de": "IT-Administration & Support", "en": "IT administration & support"},
        "roles": [
            {
                "name": "Administration",
                "keywords": [
                    "administrator",
                    "sysadmin",
                    "systemadministrat",
                    "fachinformatiker",
                    "systemintegration",
                ],
            },
            {"name": "Netzwerk", "keywords": ["network", "netzwerk", "firewall"]},
            {
                "name": "Support",
                "keywords": ["it support", "it-support", "helpdesk", "service desk", "it-spezialist"],
            },
            {"name": "IT", "keywords": ["it engineer", "it-engineer", "it specialist", "it consultant"]},
        ],
        "excludes": ["sales", "account", "salesforce", "sap "],
        "skills": [
            "windows server",
            "active directory",
            "linux",
            "vmware",
            "microsoft 365",
            "intune",
            "cisco",
            "powershell",
        ],
        "search_queries": ["system administrator", "it support", "network engineer"],
    },
    "product": {
        "label": {"de": "Produkt & Design", "en": "Product & design"},
        "roles": [
            {"name": "Product", "keywords": ["product manager", "product owner", "produktmanager"]},
            {"name": "Design", "keywords": ["ux", "ui designer", "product designer", "interaction designer"]},
            {"name": "Research", "keywords": ["user research", "ux research"]},
        ],
        "excludes": ["sales", "account", "recruit"],
        "skills": ["figma", "user research", "prototyping", "roadmap", "jira", "a/b testing", "analytics"],
        "search_queries": ["product manager", "product designer", "ux designer"],
    },
}


def preset(name: str) -> dict[str, Any]:
    return PRESETS.get(name, PRESETS["cloud"])


def presets_for_ui() -> list[dict[str, Any]]:
    return [{"id": key, **value} for key, value in PRESETS.items()]
