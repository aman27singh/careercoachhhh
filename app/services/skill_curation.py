"""
Curated learning resources and projects for key skills.
"""

SKILL_CURATION = {
    "aws": {
        "learning_resources": [
            "AWS Skill Builder Cloud Essentials",
            "AWS Well-Architected Framework overview",
            "IAM and VPC basics",
        ],
        "recommended_project": {
            "title": "Deploy a Serverless API",
            "description": "Build and deploy a serverless API with Lambda and API Gateway.",
            "steps": [
                "Create IAM roles and policies",
                "Build a Lambda function",
                "Expose it with API Gateway",
                "Add logging and monitoring",
            ],
        },
        "checkpoints": [
            "Explain IAM roles vs policies",
            "Deploy a Lambda function",
            "Secure an API with API keys",
        ],
    },
    "docker": {
        "learning_resources": [
            "Docker getting started guide",
            "Dockerfile and image layers",
            "Container networking basics",
        ],
        "recommended_project": {
            "title": "Containerize a FastAPI App",
            "description": "Package a FastAPI app with Docker and run it locally.",
            "steps": [
                "Write a Dockerfile",
                "Build and run the image",
                "Add environment variables",
                "Use docker-compose for local dev",
            ],
        },
        "checkpoints": [
            "Build a Docker image",
            "Run and expose a container port",
            "Understand volume mounts",
        ],
    },
    "api": {
        "learning_resources": [
            "REST API design principles",
            "HTTP status codes and semantics",
            "API versioning basics",
        ],
        "recommended_project": {
            "title": "Design a CRUD API",
            "description": "Create a CRUD API with clear resource modeling.",
            "steps": [
                "Define resource endpoints",
                "Implement validation and errors",
                "Add pagination and filtering",
                "Document with OpenAPI",
            ],
        },
        "checkpoints": [
            "Map resources to endpoints",
            "Return correct HTTP status codes",
            "Document an endpoint",
        ],
    },
    "java": {
        "learning_resources": [
            "Java language fundamentals",
            "Collections and generics",
            "Spring Boot basics",
        ],
        "recommended_project": {
            "title": "Spring Boot REST Service",
            "description": "Build a REST service using Spring Boot and JPA.",
            "steps": [
                "Create a Spring Boot project",
                "Add JPA entities",
                "Implement REST controllers",
                "Add tests with JUnit",
            ],
        },
        "checkpoints": [
            "Create a REST endpoint",
            "Map entities with JPA",
            "Write a unit test",
        ],
    },
    "python": {
        "learning_resources": [
            "Python core syntax and data structures",
            "Virtual environments and packaging",
            "Type hints and linting basics",
        ],
        "recommended_project": {
            "title": "CLI Data Tool",
            "description": "Build a CLI tool to parse and analyze CSV data.",
            "steps": [
                "Parse arguments",
                "Read and transform CSV data",
                "Generate summary output",
                "Add unit tests",
            ],
        },
        "checkpoints": [
            "Write functions with type hints",
            "Handle file I/O safely",
            "Create a small CLI command",
        ],
    },
    "sql": {
        "learning_resources": [
            "SQL SELECT and JOIN basics",
            "Indexes and query performance",
            "Data modeling fundamentals",
        ],
        "recommended_project": {
            "title": "Analytics Query Pack",
            "description": "Write a set of analytics queries on a sample dataset.",
            "steps": [
                "Design tables with relationships",
                "Write JOIN-heavy queries",
                "Add aggregations and windows",
                "Optimize a slow query",
            ],
        },
        "checkpoints": [
            "Write a JOIN query",
            "Use GROUP BY with HAVING",
            "Explain a query plan",
        ],
    },
    "kubernetes": {
        "learning_resources": [
            "Kubernetes architecture overview",
            "Pods, deployments, and services",
            "ConfigMaps and Secrets",
        ],
        "recommended_project": {
            "title": "Deploy a Web App to Kubernetes",
            "description": "Deploy a containerized app with a service and ingress.",
            "steps": [
                "Create deployment and service",
                "Configure environment variables",
                "Set up ingress",
                "Scale and monitor",
            ],
        },
        "checkpoints": [
            "Create a deployment",
            "Expose a service",
            "Scale replicas",
        ],
    },
    "react": {
        "learning_resources": [
            "React component fundamentals",
            "State and effects",
            "Routing and data fetching",
        ],
        "recommended_project": {
            "title": "Dashboard UI",
            "description": "Build a dashboard with charts and API data.",
            "steps": [
                "Set up routes",
                "Build reusable components",
                "Fetch and display data",
                "Add basic tests",
            ],
        },
        "checkpoints": [
            "Build a component with state",
            "Handle form input",
            "Fetch data with hooks",
        ],
    },
}


def get_skill_curation(skill_key: str) -> dict:
    curated = SKILL_CURATION.get(skill_key)
    if curated:
        return curated

    return {
        "learning_resources": [
            "Skill overview and fundamentals",
            "Core concepts and best practices",
            "Hands-on tutorials and exercises",
        ],
        "recommended_project": {
            "title": "Capstone Mini Project",
            "description": "Build a small project applying key concepts.",
            "steps": [
                "Define requirements",
                "Implement core features",
                "Test and document",
            ],
        },
        "checkpoints": [
            "Explain core concepts",
            "Build a small working example",
            "Review common pitfalls",
        ],
    }
