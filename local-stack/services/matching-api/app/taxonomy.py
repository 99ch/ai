"""Normalisation de compétences, sur le même principe multi-couches qu'AI
Real-Time : un dictionnaire de synonymes métier fait main (prioritaire),
complété par trois couches de repli plus larges, chacune moins prioritaire
que la précédente -- ROME (France Travail), puis ESCO (UE), puis O*NET/e-CF
(États-Unis/UE) : voir _build_lookup().

_TECH_SKILLS ci-dessous est un portage quasi intégral du `_SKILLS` d'AI
Real-Time (backend/app/services/taxonomy.py), en deux vagues :
- 2026-09-15 (point16) : leur dictionnaire de l'époque (281 entrées).
- 2026-09-17 (point17) : leur expansion massive suivante -- 303 entrées
  manuelles supplémentaires + trois audits sur données réelles (67 offres
  d'emploi réelles, 33 574 profils candidats réels, 1500 CV pour valider
  les nouvelles couches ROME/ESCO/O*NET/e-CF) -- portée intégralement via
  extraction AST du fichier source (pas de retranscription manuelle, pour
  éviter tout risque de coquille sur ~450 nouvelles entrées).

Pas leur couche ESCO/FAISS *historique* (esco_taxonomy.py, un POC jamais
branché sur leur moteur de scoring réel matcher.py -- voir leur propre
docstring "POC additif, pas encore adopté"). La couche ESCO portée ici
(_esco_skills(), point17) est DIFFÉRENTE : un import filtré et pré-généré
(esco_skills_data.json, ~1916 compétences) qu'AI Real-Time a ajouté
ensuite spécifiquement pour alimenter leur VRAI pipeline (parser.py ->
taxonomy.py), au même niveau que ROME.

Trouvé en auditant Keoni sur un échantillon de CV/offres réels
(2026-09-15) : l'ancien dictionnaire, volontairement restreint au
développement web, ratait toute compétence des domaines gouvernance/
risque/conformité/assurance/RH/finance/juridique/logistique/santé/BTP —
exactement les domaines que ce portage couvre. Une entrée propre à Keoni
sans équivalent chez AI Real-Time est conservée en fin de dictionnaire
(Développeur Web).

rome_skills_data.json est un export ouvert du référentiel ROME 4.0
("savoir"), scope "3DS MAX" -> ["3ds max"] : libellé canonique -> alias.
esco_skills_data.json, onet_skills_data.json et ecf_skills_data.json sont
copiés tels quels depuis AI Real-Time (générés par eux hors-ligne, script
de génération non commité de leur côté non plus -- même convention que
rome_skills_data.json).
"""

from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Dict, List

_ROME_SKILLS_PATH = Path(__file__).with_name("data") / "rome_skills_data.json"
_ESCO_SKILLS_PATH = Path(__file__).with_name("data") / "esco_skills_data.json"
_ONET_SKILLS_PATH = Path(__file__).with_name("data") / "onet_skills_data.json"
_ECF_SKILLS_PATH = Path(__file__).with_name("data") / "ecf_skills_data.json"
_TOKEN_RE = re.compile(r"[^\s,;/()|'’]+")
_MAX_NGRAM = 5

# canonique -> alias (minuscules, sans accents attendu après _fold()).
# Portage verbatim du `_SKILLS` d'AI Real-Time (voir docstring du module),
# organisé par domaine comme chez eux.
_TECH_SKILLS: Dict[str, List[str]] = {
    # ── INFORMATIQUE & TECH ────────────────────────────────────────────────
    "Python": ["python", "py"],
    "JavaScript": ["javascript", "js", "ecmascript", "es6", "es6+", "es2015", "vanilla js"],
    "TypeScript": ["typescript", "ts"],
    "PHP": ["php", "php 7", "php 8", "php7", "php8"],
    "Symfony": ["symfony", "symfony framework"],
    "Java": ["java"],
    "C#": ["c#", "csharp", "c sharp"],
    ".NET": [".net", "dotnet", "dot net", "asp.net", "asp net", ".net core"],
    "C++": ["c++", "cplusplus", "c plus plus"],
    "Ruby": ["ruby", "ruby on rails", "rails"],
    "Golang": ["golang", "go lang", "go programming"],
    "Rust": ["rust"],
    "Swift": ["swift"],
    "Kotlin": ["kotlin"],
    "Scala": ["scala"],
    "R": ["r stats", "langage r"],
    "SQL": ["sql", "structured query language"],
    "SQL Server": ["sql server", "ms sql server", "sqlserver", "mssql", "t-sql", "tsql"],
    "SSIS": ["ssis", "sql server integration services"],
    "SSAS": ["ssas", "sql server analysis services"],
    "SSRS": ["ssrs", "sql server reporting services"],
    "PostgreSQL": ["postgresql", "postgres", "psql"],
    "MySQL": ["mysql", "maria db", "mariadb"],
    "Oracle DB": ["oracle", "oracle database", "oracle db", "pl/sql"],
    "DB2": ["db2", "ibm db2"],
    "Snowflake": ["snowflake"],
    "QlikSense": ["qliksense", "qlik sense", "qlik"],
    "QlikView": ["qlikview", "qlik view"],
    "Talend": ["talend", "talend etl", "talend open studio"],
    "Informatica": ["informatica", "informatica powercenter", "powercenter", "iics", "informatica intelligent cloud services"],
    "Business Objects": ["business objects", "businessobjects", "sap bo", "sap businessobjects", "bo xir2", "bo xi", "xir2", "xi r2"],
    "WebIntelligence": ["webintelligence", "webi", "web intelligence"],
    # Bare "sas" exclu : suffixe juridique français très courant (Société
    # par Actions Simplifiée, ex. "ACME SAS") -- même risque de faux positif
    # que le "recette" nu écarté plus bas. Seuls les noms de produit
    # qualifiés ci-dessous sont sans ambiguïté.
    "SAS (logiciel)": ["sas base", "sas enterprise guide", "sas grid"],
    "Power Query": ["power query", "powerquery", "power query m", "scripts m"],
    "MongoDB": ["mongodb", "mongo"],
    "Redis": ["redis"],
    "Elasticsearch": ["elasticsearch", "opensearch", "elastic"],
    "Kafka": ["kafka", "apache kafka", "kafka streams", "kafka connect"],
    "RabbitMQ": ["rabbitmq", "rabbit mq", "amqp"],
    "Blockchain": ["solidity", "web3", "web3.js", "web3js", "dapp", "dapps", "smart contract", "smart contracts", "ethereum", "blockchain"],
    "HTML/CSS": ["html", "html5", "css", "css3", "sass", "scss", "tailwind", "tailwindcss", "bootstrap", "styled components"],
    "React": ["react", "react.js", "reactjs", "react js", "redux", "react redux", "react hooks", "jsx", "react native"],
    "Angular": ["angular", "angularjs", "ngrx", "rxjs", "angular js"],
    "Vue.js": ["vue.js", "vuejs", "vue js", "vuex", "pinia", "vue 3", "vue 2"],
    "Node.js": ["node", "nodejs", "node.js", "node js"],
    "Next.js": ["next.js", "nextjs", "next js"],
    "Express.js": ["express.js", "expressjs", "express js", "express"],
    "NestJS": ["nestjs", "nest.js", "nest js"],
    "FastAPI": ["fastapi", "fast api"],
    "Django": ["django"],
    "Flask": ["flask"],
    "Spring Boot": ["spring", "spring boot", "springframework"],
    "Laravel": ["laravel"],
    "Docker": ["docker", "containerisation", "containerization"],
    "Kubernetes": ["kubernetes", "k8s", "kubectl"],
    "AWS": ["aws", "amazon web services", "amazon cloud"],
    "Azure": ["azure", "microsoft azure"],
    "GCP": ["gcp", "google cloud", "google cloud platform"],
    "Terraform": ["terraform", "iac", "infrastructure as code"],
    "Ansible": ["ansible"],
    "CI/CD": ["cicd", "ci/cd", "github actions", "gitlab ci", "jenkins", "devops pipeline", "circleci", "circle ci", "travis ci", "travis"],
    "Git": ["git", "github", "gitlab", "bitbucket", "bitbuckets", "versioning", "version control"],
    "SVN": ["svn", "subversion", "apache subversion"],
    "Linux": ["linux", "ubuntu", "debian", "centos", "bash", "shell scripting", "unix"],
    "Machine Learning": ["machine learning", "ml", "apprentissage automatique", "apprentissage machine"],
    "Deep Learning": ["deep learning", "dl", "apprentissage profond", "reseau de neurones", "neural network"],
    "NLP": ["nlp", "natural language processing", "traitement du langage naturel", "traitement du langage"],
    "Data Science": ["data science", "datascience", "science des donnees"],
    "Data Engineering": ["data engineering", "ingenierie des donnees", "pipeline de donnees", "etl", "elt", "data management"],
    "Power BI": ["power bi", "powerbi"],
    "Tableau": ["tableau", "tableau software"],
    "SAP": ["sap", "sap erp", "sap hana", "sap r3", "sap r/3"],
    "Salesforce": ["salesforce", "sfdc", "crm salesforce"],
    "Cybersécurité": ["cybersecurite", "cybersecurity", "securite informatique", "pentest", "securite reseau", "soc", "siem", "owasp", "csrf", "xss", "vulnerabilites", "vulnerabilite"],
    "ISO 27001": ["iso 27001", "iso27001", "norme iso 27001"],
    "ISO 27005": ["iso 27005", "iso27005"],
    "ISO 42001": ["iso 42001", "iso42001"],
    "EBIOS": ["ebios", "ebios rm", "methode ebios"],
    # "dora" nu entre en collision avec le prénom (find_skills replie la
    # casse, donc "Dora" la personne == "DORA" le règlement) -- même classe
    # de risque que "c"/"son" côté import ROME, mais pas exclu : contrairement
    # à ces deux mots-outils quasi omniprésents en français, une mention
    # fortuite du prénom est rare dans un texte de CV/offre, et l'acronyme
    # est justement la façon dont un vrai CV GRC/finance le liste (nu, à
    # côté de NIS2/SOX/PCI-DSS sans contexte). Retirer l'alias nu le
    # rendrait indétectable dans ce cas réel. Compromis assumé.
    "DORA": ["dora", "digital operational resilience act"],
    "NIS2": ["nis2", "nis 2", "directive nis2"],
    "CISA": ["cisa", "certified information systems auditor"],
    "PCI-DSS": ["pci-dss", "pci dss", "pcidss"],
    "SMSI": ["smsi", "isms"],
    "IAM": ["iam", "identity and access management", "gestion des identites et des acces", "gestion des identites"],
    "PKI": ["pki", "infrastructure a cles publiques", "infrastructures a cles publiques"],
    "COBIT": ["cobit", "cobit 5", "cobit 5.0", "cobit 2019"],
    "ISAE 3402": ["isae 3402", "isae3402"],
    "SOX": ["sox", "sarbanes-oxley", "sarbanes oxley"],
    "Accessibilité web": ["accessibilite", "accessibility", "accessibilite web", "accessibilite numerique",
                          "wcag", "wcag 2", "wcag 2.0", "wcag 2.1", "wcag 2.2", "wcagrgaa",
                          "rgaa", "rgaa 4", "rgaa 4.1", "a11y", "wai-aria", "aria",
                          "opquast", "axe", "axe-core", "lighthouse a11y"],
    "Monitoring": ["monitoring", "observabilite", "observability", "supervision", "apm"],
    "Prometheus": ["prometheus"],
    "Grafana": ["grafana"],
    "Datadog": ["datadog"],
    "Sentry": ["sentry"],
    "SonarQube": ["sonarqube", "sonar", "sonarcloud", "code quality", "code coverage", "qualite du code"],
    "API REST": ["api", "rest", "restful", "api rest", "web services", "webservices", "json"],
    "SOAP/XML Web Services": ["soap", "wsdl"],
    "Microservices": ["microservices", "microservice", "architecture microservices"],
    "GraphQL": ["graphql", "apollo", "apollo server", "apollo client"],
    "WebSockets": ["websocket", "websockets", "socket.io", "socketio", "ws", "grpc", "grpc"],
    "Agile": ["agile", "methode agile", "agilite", "safe", "safe framework", "scaled agile", "scaled agile framework"],
    "Scrum": ["scrum", "scrum master", "kanban"],
    "Product Owner": ["po", "product owner"],
    "ITIL": ["itil", "itil v3", "itil v4", "service level management", "slm", "service level manager", "itsm", "service desk"],
    "ServiceNow": ["servicenow", "service now", "snow"],
    "Jira": ["jira", "atlassian"],
    "Confluence": ["confluence"],
    "Excel avancé": ["excel", "microsoft excel", "tableur", "macros excel", "google sheets"],
    "VBA": ["vba", "visual basic for applications", "visual basic"],
    "Tests automatisés": ["jest", "cypress", "playwright", "selenium", "phpunit", "junit", "mocha", "chai",
                          "supertest", "newman", "vitest", "pytest", "test unitaire", "tests unitaires",
                          "test integration", "tests integration", "tests e2e", "tdd", "bdd",
                          "qa", "istqb", "uat", "assurance qualite logicielle",
                          "tests de recette"],
    "Business Intelligence": ["bi", "business intelligence", "informatique decisionnelle"],
    "Data Analyst": ["data analyst", "analyste de donnees", "analyste donnees"],
    "ORM": ["orm", "object-relational mapping", "object relational mapping"],
    "Développeur Full Stack": ["full stack", "fullstack", "full-stack"],
    "Frontend": ["frontend", "front-end", "front end"],
    "Back-office": [
        "backoffice", "back-office", "back office",
        "backoffices", "back-offices", "back offices",
    ],
    "ERP": ["erp", "enterprise resource planning", "progiciel de gestion integre", "pgi"],
    "UML": ["uml", "unified modeling language"],
    "UX/UI Design": ["ux", "ui", "ux design", "ui design", "user experience", "user interface",
                      "ihm", "interface homme machine"],
    "TMA": ["tma", "tierce maintenance applicative"],
    "SGBD": ["sgbd", "systeme de gestion de base de donnees", "dbms", "base de donnees", "bases de donnees"],
    "J2EE": ["j2ee", "jee", "java ee", "java enterprise edition"],
    "JPA": ["jpa", "java persistence api"],
    "JSF": ["jsf", "java server faces"],
    "MVC": ["mvc", "model view controller"],
    "SSO": ["sso", "single sign on", "authentification unique"],
    "ALM": ["alm", "application lifecycle management", "hp alm"],
    "GLPI": ["glpi"],
    "SCCM": ["sccm", "system center configuration manager"],
    "TFS": ["tfs", "team foundation server"],
    "Cisco": ["cisco", "ccna", "certification ccna", "cisco systems"],
    "VMware": ["vmware", "vsphere", "esxi"],
    "MDM": ["mdm", "master data management", "mobile device management"],
    "RSSI": ["rssi", "responsable securite des systemes d information"],
    "SEPA": ["sepa", "virement sepa", "prelevement sepa"],
    "SOA": ["soa", "architecture orientee services"],
    "KYC": ["kyc", "know your customer"],
    "Continuité d'activité": ["pca", "pra", "plan de continuite d activite",
                               "plan de reprise d activite", "disaster recovery"],
    "Cloud Computing": ["cloud", "cloud computing", "informatique en nuage"],
    "DevOps": ["devops", "dev ops"],
    "RPA": ["rpa", "robotic process automation", "automatisation robotisee des processus"],
    "GPO": ["gpo", "group policy object", "strategie de groupe"],
    "BPM": ["bpm", "business process management", "gestion des processus metier"],
    "WAF": ["waf", "web application firewall"],
    "Réseaux informatiques": ["vpn", "dns", "dhcp", "lan", "wan", "mpls", "vlan", "ssh",
                               "ftp", "sftp", "ospf", "san", "ldap", "tcp ip"],

    # ── TECH (COMPLÉMENT 2026-09-17) : data/IA, cloud, DevOps, mobile, ────
    # tests, cybersécurité, réseaux, design, IoT, jeu vidéo, architecture,
    # low-code, marketing tech. Portage verbatim d'AI Real-Time (b16d32e) :
    # chaque alias déjà vérifié par eux contre le risque de collision avec
    # un mot français/anglais ordinaire (ex: "solid"/"pandas"/"sketch"
    # gardés uniquement sous leur forme qualifiée, "Consul" sans alias nu
    # -- collision avec le mot français "consul").
    "Scikit-learn": ["scikit learn", "scikit-learn", "sklearn"],
    "Pandas": ["pandas dataframe", "pandas python"],
    "NumPy": ["numpy"],
    "Jupyter": ["jupyter", "jupyter notebook", "jupyterlab"],
    "Hugging Face": ["hugging face", "huggingface", "transformers library"],
    "LangChain": ["langchain"],
    "LLM": ["grands modeles de langage", "large language model", "large language models", "llm"],
    "IA Générative": ["genai", "generative ai", "ia generative"],
    "Prompt Engineering": ["conception de prompts", "ingenierie de prompt", "prompt engineering"],
    "RAG": ["rag", "rag llm", "retrieval augmented generation"],
    "Base de données vectorielle": ["base de donnees vectorielle", "chromadb", "faiss", "milvus", "pinecone", "vector database", "weaviate"],
    "OpenAI API": ["chatgpt api", "gpt-4", "gpt4", "openai api"],
    "Computer Vision": ["computer vision", "opencv"],
    "MLOps": ["mlflow", "mlops"],
    "XGBoost": ["xgboost"],
    "LightGBM": ["lightgbm"],
    "Reinforcement Learning": ["apprentissage par renforcement", "reinforcement learning"],
    "Feature Engineering": ["feature engineering", "ingenierie des caracteristiques"],
    "Databricks": ["databricks"],
    "PySpark": ["py spark", "pyspark"],
    "dbt": ["data build tool", "dbt"],
    "Apache Flink": ["apache flink", "flink"],
    "Presto/Trino": ["presto db", "presto/trino", "trino sql"],
    "ClickHouse": ["clickhouse"],
    "AWS Lambda": ["amazon lambda", "aws lambda"],
    "Amazon S3": ["amazon s3", "aws s3"],
    "Amazon RDS": ["amazon rds", "aws rds"],
    "Amazon EKS": ["amazon eks", "aws eks", "elastic kubernetes service"],
    "Amazon ECS": ["amazon ecs", "aws ecs", "elastic container service"],
    "Amazon SQS": ["amazon sqs", "aws sqs"],
    "Amazon SNS": ["amazon sns", "aws sns"],
    "Amazon CloudFront": ["amazon cloudfront", "aws cloudfront"],
    "Amazon VPC": ["amazon vpc", "aws vpc"],
    "Amazon Route 53": ["amazon route 53", "aws route53", "route 53"],
    "Azure Functions": ["azure functions"],
    "Azure DevOps": ["azure devops"],
    "AKS": ["aks", "aks cluster", "azure kubernetes service"],
    "Azure Cosmos DB": ["azure cosmos db", "cosmosdb"],
    "Azure Blob Storage": ["azure blob storage", "blob storage"],
    "Google BigQuery": ["bigquery", "google bigquery"],
    "Google Cloud Functions": ["cloud functions gcp", "google cloud functions"],
    "GKE": ["gke", "gke cluster", "google kubernetes engine"],
    "Google Pub/Sub": ["google pub sub", "google pub/sub", "pub/sub gcp"],
    "Multi-cloud": ["cloud hybride", "hybrid cloud", "multi-cloud", "multicloud"],
    "Helm": ["helm", "helm charts", "helm kubernetes"],
    "ELK Stack": ["elk stack", "kibana", "logstash"],
    "HashiCorp Vault": ["hashicorp vault", "vault secrets"],
    # "Consul" (HashiCorp) sans alias nu : collision avec le mot français
    # "consul" (représentant diplomatique) -- même risque que "chef"/"sas".
    "Consul": ["hashicorp consul"],
    "ArgoCD": ["argo cd", "argocd"],
    "GitOps": ["gitops"],
    "Istio": ["istio", "istio service mesh"],
    "Service Mesh": ["maillage de services", "service mesh"],
    "Nginx": ["nginx"],
    "Apache HTTP Server": ["apache http server", "apache2", "httpd"],
    "HAProxy": ["haproxy"],
    "Load Balancing": ["equilibrage de charge", "load balancing", "repartition de charge"],
    "Packer": ["hashicorp packer", "packer"],
    "Site Reliability Engineering": ["site reliability engineering", "sre"],
    "SwiftUI": ["swiftui"],
    "Jetpack Compose": ["jetpack compose"],
    "Flutter": ["dart", "flutter"],
    "Xamarin": ["xamarin"],
    "Ionic": ["ionic", "ionic framework"],
    "Neo4j": ["base de donnees graphe", "graph database", "neo4j"],
    "InfluxDB": ["base de donnees temporelle", "influxdb", "time series database"],
    "CouchDB": ["apache couchdb", "couchdb"],
    "JMeter": ["apache jmeter", "jmeter"],
    "Gatling": ["gatling", "gatling load testing"],
    "k6": ["grafana k6", "k6", "k6 load testing"],
    "Appium": ["appium", "appium mobile testing"],
    "Robot Framework": ["robot framework"],
    "Burp Suite": ["burp suite", "burpsuite"],
    "Nmap": ["nmap"],
    "SOAR": ["security orchestration", "soar", "soar security"],
    "EDR": ["edr", "edr endpoint", "endpoint detection and response"],
    "XDR": ["extended detection and response", "xdr", "xdr security"],
    "Zero Trust": ["architecture zero trust", "zero trust"],
    "MFA": ["2fa", "authentification a deux facteurs", "authentification multifacteur", "mfa"],
    "OAuth": ["oauth", "oauth 2.0", "oauth2"],
    "OpenID Connect": ["oidc", "openid connect"],
    "JWT": ["json web token", "jwt"],
    "TLS/SSL": ["certificat ssl", "certificat tls", "ssl", "tls", "tls/ssl"],
    "IDS/IPS": ["ids ips", "ids/ips", "intrusion detection system", "intrusion prevention system"],
    "Threat Intelligence": ["renseignement sur la menace", "threat intelligence"],
    "Red Team / Blue Team": ["blue team", "purple team", "red team", "red team / blue team"],
    "CTF": ["capture the flag", "ctf", "ctf hacking"],
    "CVE": ["common vulnerabilities and exposures", "cve"],
    "Bug Bounty": ["bug bounty"],
    "Firewall Palo Alto": ["firewall palo alto", "palo alto firewall", "palo alto networks"],
    "Fortinet": ["fortigate", "fortinet"],
    "Check Point": ["check point", "check point firewall", "checkpoint firewall"],
    "SD-WAN": ["sd-wan", "sdwan"],
    "CDN": ["cdn", "content delivery network", "reseau de diffusion de contenu"],
    "IPv6": ["ipv6"],
    # "Sketch" sans alias nu : "sketch" est aussi un mot français courant
    # (sketch comique).
    "Sketch": ["sketch app design"],
    "Adobe XD": ["adobe xd"],
    "InVision": ["invision", "invision app"],
    "Arduino": ["arduino"],
    "Raspberry Pi": ["raspberry pi"],
    "RTOS": ["real time operating system", "rtos", "systeme d exploitation temps reel"],
    "MQTT": ["mqtt"],
    "IoT": ["internet of things", "iot", "objets connectes"],
    "Unity": ["unity", "unity 3d", "unity engine"],
    "Godot": ["godot", "godot engine"],
    "Design Patterns": ["design patterns", "patrons de conception"],
    # "SOLID" sans alias nu : "solid" est un mot anglais très courant dans
    # les phrases de CV ("solid experience", "solid understanding of...").
    "SOLID": ["principes solid", "solid principles"],
    "Domain-Driven Design": ["ddd", "domain driven design", "domain-driven design"],
    "Event-Driven Architecture": ["architecture evenementielle", "event-driven architecture"],
    "Architecture Hexagonale": ["architecture hexagonale", "hexagonal architecture", "ports and adapters"],
    "CQRS": ["command query responsibility segregation", "cqrs"],
    "Clean Code": ["clean code", "code propre"],
    "Power Apps": ["microsoft power apps", "power apps"],
    "Bubble.io": ["bubble no-code", "bubble.io"],
    "Airtable": ["airtable"],
    "Zapier": ["zapier"],
    "Make (Integromat)": ["integromat", "make (integromat)", "make automation"],
    "Google Tag Manager": ["google tag manager", "gtm"],
    "SEO/SEA": ["ahrefs", "referencement payant", "semrush", "seo/sea"],
    "FFmpeg": ["ffmpeg"],
    "WebRTC": ["webrtc"],

    # ── GESTION DE PROJET & MANAGEMENT ────────────────────────────────────
    "Gestion de projet": ["gestion de projet", "project management", "chef de projet", "pilotage de projet", "project manager"],
    "Leadership": ["leadership", "direction d equipe", "team leadership", "encadrement"],
    "Management d'équipe": ["management d equipe", "team management", "encadrement d equipe", "gestion d equipe", "people management"],
    "Conduite du changement": ["conduite du changement", "change management", "transformation organisationnelle"],
    "PMO": ["pmo", "project management office", "bureau de projet"],
    "Prince2": ["prince2", "prince 2"],
    "PMP": ["pmp", "project management professional"],
    "Budget": ["budget", "gestion budgetaire", "budget management", "controle budgetaire"],
    "Reporting": ["reporting", "tableau de bord", "tableaux de bord", "kpi", "indicateurs de performance", "dashboard"],
    "Planification": ["planification", "planning", "ordonnancement", "gantt", "planner"],
    "Coordination": ["coordination", "coordination d equipe", "coordination de projet"],
    "Communication": ["communication", "communication professionnelle", "communication orale", "communication ecrite"],
    "Négociation": ["negociation", "negotiation", "techniques de negociation"],
    "Présentation": ["presentation", "prise de parole", "powerpoint", "pitch"],
    "Résolution de problèmes": ["resolution de problemes", "problem solving", "analyse de problemes"],
    "Coaching": ["coaching", "mentoring", "mentorat", "accompagnement"],
    "Formation": ["developpement des competences", "animation de formation", "plan de formation professionnelle"],
    "Stratégie": ["strategic planning", "planification strategique", "vision strategique", "plan strategique"],
    "Gouvernance": ["gouvernance", "governance", "pilotage", "controle interne"],
    "Parties prenantes": ["parties prenantes", "stakeholders", "stakeholder management", "gestion des parties prenantes"],
    "Cycle en V": ["cycle en v", "v-model", "v model"],

    # ── MANAGEMENT (COMPLÉMENT 2026-09-17) : outils, méthodologies, ──────
    # gouvernance, certifications, leadership, entrepreneuriat. Portage
    # verbatim d'AI Real-Time (b16d32e), même discipline anti-collision que
    # le lot tech (ex: "notion"/"miro"/"delegation" gardés uniquement sous
    # forme qualifiée).
    "Trello": ["trello"],
    "Asana": ["asana"],
    "Monday.com": ["monday.com", "monday com"],
    "Microsoft Project": ["microsoft project", "ms project", "msproject"],
    "Smartsheet": ["smartsheet"],
    "Notion": ["notion app", "outil notion"],
    "ClickUp": ["clickup", "click up"],
    "Wrike": ["wrike"],
    "Basecamp": ["basecamp"],
    "OpenProject": ["openproject"],
    "Miro": ["miro board", "tableau miro"],
    "OKR": ["okr", "objectifs et resultats cles", "objectives and key results"],
    "Balanced Scorecard": ["balanced scorecard", "tableau de bord prospectif"],
    "Analyse SWOT": ["swot", "analyse swot", "forces faiblesses opportunites menaces"],
    "PESTEL": ["pestel", "analyse pestel"],
    "Business Model Canvas": ["business model canvas", "bmc"],
    "Value Proposition Canvas": ["value proposition canvas"],
    "Benchmarking": ["benchmarking", "benchmark concurrentiel"],
    "TQM": ["tqm", "total quality management", "management total de la qualite"],
    "5S": ["methode 5s", "5s lean"],
    "PDCA": ["pdca", "roue de deming", "plan do check act"],
    "TPM (maintenance)": ["total productive maintenance", "maintenance productive totale"],
    "Value Stream Mapping": ["value stream mapping", "cartographie des flux de valeur"],
    "Hoshin Kanri": ["hoshin kanri"],
    "Diagramme d'Ishikawa": ["ishikawa", "diagramme d ishikawa", "diagramme causes effets", "arete de poisson"],
    "COSO": ["coso", "cadre coso", "coso framework"],
    "ISO 31000": ["iso 31000"],
    "Due diligence": ["due diligence", "audit d acquisition"],
    "MBA": ["mba", "master of business administration"],
    "Executive MBA": ["executive mba", "emba"],
    "MSP (Managing Successful Programmes)": ["managing successful programmes"],
    "P3O": ["p3o"],
    "Gestion de programme": ["gestion de programme", "program management", "programme management"],
    "Gestion de portefeuille de projets": ["gestion de portefeuille de projets", "portfolio management"],
    "Comité de direction": ["comite de direction", "codir", "comex", "comite executif"],
    "Business Unit Management": ["business unit management", "gestion de business unit", "direction de business unit"],
    "Pilotage d'activité": ["pilotage d activite", "pilotage operationnel"],
    # "Fusions et acquisitions" existe déjà (ROME) sous ce nom exact ; on
    # ajoute seulement les alias manquants sans créer de canonical rival.
    "Fusions et acquisitions": ["m&a", "mergers and acquisitions"],
    "Leadership transformationnel": ["leadership transformationnel", "transformational leadership"],
    "Leadership situationnel": ["leadership situationnel", "situational leadership"],
    "Servant Leadership": ["servant leadership", "leadership serviteur"],
    "Management bienveillant": ["management bienveillant", "management participatif"],
    "Gestion des fournisseurs": ["gestion des fournisseurs", "vendor management", "supplier management"],
    "Gestion des sous-traitants": ["gestion des sous-traitants", "management de sous-traitance"],
    "Gestion de contrats": ["gestion de contrats", "contract management", "suivi contractuel"],
    "Priorisation": ["priorisation", "prioritization", "matrice d eisenhower"],
    "Prise de décision": ["prise de decision", "decision making", "aide a la decision"],
    "Délégation": ["delegation de taches", "delegation d equipe"],
    "Entrepreneuriat": ["entrepreneuriat", "creation d entreprise", "esprit entrepreneurial"],
    "Intrapreneuriat": ["intrapreneuriat", "intrapreneur"],
    "Business Plan": ["business plan", "plan d affaires"],
    "Levée de fonds": ["levee de fonds", "fundraising", "capital-risque", "venture capital"],

    # ── COMMERCIAL & VENTE ────────────────────────────────────────────────
    "Développement commercial": ["developpement commercial", "business development", "bizdev", "developpement des affaires", "business developer"],
    "Vente": ["vente", "sales", "commercialisation", "acte de vente", "vendeur", "commercial"],
    "Prospection": ["prospection", "prospection commerciale", "cold calling", "demarchage", "teleprospection"],
    "CRM": ["crm", "gestion de la relation client", "customer relationship management", "hubspot", "pipedrive", "zoho"],
    "Account Management": ["account management", "gestion de compte", "key account", "grands comptes", "account manager", "kam"],
    "Service client": ["service client", "customer service", "relation client", "satisfaction client", "customer success", "customer care"],
    "Fidélisation": ["fidelisation", "retention", "retention client", "programme fidelite"],
    "Appel d'offres": ["appel d offres", "reponse a appel d offres", "ao", "rfp", "appel d offre"],
    "Vente B2B": ["vente b2b", "b2b", "business to business", "vente entreprise"],
    "Vente B2C": ["vente b2c", "b2c", "business to consumer", "vente au detail", "vente en magasin"],
    "Trade marketing": ["trade marketing", "animation reseau", "sell-out", "merchandising"],
    "Force de vente": ["force de vente", "animation equipe commerciale", "coaching commercial"],

    # ── COMMERCIAL (COMPLÉMENT 2026-09-17) ───────────────────────────────
    "SPIN Selling": ["spin selling", "methode spin"],
    "Challenger Sale": ["challenger sale", "vente challenger"],
    "Solution Selling": ["solution selling", "vente de solutions"],
    "Social Selling": ["social selling", "vente sociale"],
    "Vente à distance": ["vente a distance", "televente"],
    "Techniques de closing": ["closing commercial", "techniques de closing"],
    "Vente export": ["vente export", "export sales", "developpement export"],
    "Sales Navigator": ["sales navigator", "linkedin sales navigator"],
    "Gestion de rayon": ["gestion de rayon", "chef de rayon"],

    # ── MARKETING & COMMUNICATION ──────────────────────────────────────────
    "Marketing digital": ["marketing digital", "digital marketing", "marketing en ligne", "web marketing"],
    "SEO": ["seo", "referencement naturel", "search engine optimization", "referencement"],
    "SEA": ["sea", "google ads", "adwords", "publicite payante", "sem", "bing ads"],
    "Réseaux sociaux": ["reseaux sociaux", "social media", "community management", "community manager"],
    "Content Marketing": ["content marketing", "marketing de contenu", "creation de contenu", "inbound marketing"],
    "Emailing": ["emailing", "email marketing", "newsletters", "mailchimp", "sendinblue", "klaviyo"],
    "Google Analytics": ["google analytics", "analytics", "analyse d audience", "web analytics", "ga4"],
    "Branding": ["branding", "image de marque", "identite de marque", "brand management"],
    "Relations presse": ["relations presse", "rp", "pr", "relations publiques", "presse"],
    "Événementiel": ["evenementiel", "organisation d evenements", "event management", "event planner"],
    "Copywriting": ["copywriting", "redaction publicitaire", "redaction web", "content writing"],
    "Design graphique": ["photoshop", "adobe photoshop", "indesign", "adobe indesign", "illustrator", "canva", "figma", "design graphique", "pao"],
    "WordPress": ["wordpress", "wp", "cms", "woocommerce", "prestashop", "shopify"],

    # ── MARKETING (COMPLÉMENT 2026-09-17) ────────────────────────────────
    "Growth Marketing": ["growth marketing", "growth hacking"],
    "Marketing Automation": ["marketing automation", "pardot", "activecampaign"],
    "Études de marché": ["etudes de marche", "market research", "etude marketing"],
    "Marketing produit": ["marketing produit", "product marketing"],
    "Influence Marketing": ["influence marketing", "marketing d influence", "influenceurs"],
    "Publicité": ["publicite", "advertising", "creation publicitaire", "campagne publicitaire"],
    "Marketing mix": ["marketing mix", "4p marketing"],
    "Persona marketing": ["persona marketing", "buyer persona"],
    "A/B Testing": ["a/b testing", "ab testing", "tests ab"],
    "Marketing international": ["marketing international"],
    "Storytelling": ["storytelling", "narration de marque", "brand storytelling"],
    "UGC (contenu généré par les utilisateurs)": ["ugc", "contenu genere par les utilisateurs", "user generated content"],

    # ── COMPTABILITÉ & FINANCE ─────────────────────────────────────────────
    "Comptabilité générale": ["comptabilite generale", "comptabilite", "accounting", "tenue de comptabilite", "comptable"],
    "Comptabilité analytique": ["comptabilite analytique", "comptabilite de gestion"],
    "Fiscalité": ["fiscalite", "tax", "droit fiscal", "tva", "impots", "declarations fiscales", "liasse fiscale"],
    "Consolidation": ["consolidation", "consolidation comptable", "etats financiers consolides", "consolidation des comptes"],
    "IFRS": ["ifrs", "normes ifrs", "normes internationales", "ias", "us gaap"],
    "Contrôle de gestion": ["controle de gestion", "controller", "controlling", "pilotage financier"],
    "Audit": ["audit", "commissariat aux comptes", "audit financier", "audit interne", "auditeur"],
    "Trésorerie": ["tresorerie", "cash management", "gestion de tresorerie", "cash flow", "plan de tresorerie"],
    "Paie": ["paie", "paye", "gestion de la paie", "bulletin de paie", "payroll", "gestionnaire de paie"],
    "Clôture comptable": ["cloture comptable", "cloture annuelle", "cloture mensuelle", "cloture des comptes"],
    "Sage": ["sage", "sage 100", "sage x3", "sage compta"],
    "Cegid": ["cegid", "cegid business", "cegid expert"],
    "SAP FI": ["sap fi", "sap fico", "sap finance", "finance erp"],
    "Analyse financière": ["analyse financiere", "financial analysis", "analyse de bilan", "analyse des ratios", "modeles financiers"],

    # ── FINANCE (COMPLÉMENT 2026-09-17) ──────────────────────────────────
    "Finance de marché": ["finance de marche", "capital markets", "salle des marches"],
    "Trading algorithmique": ["trading algorithmique", "algo trading", "high frequency trading"],
    "Gestion de patrimoine": ["gestion de patrimoine", "wealth management", "conseiller en gestion de patrimoine", "cgp"],
    # "Gestion d'actifs" (apostrophe typographique) existe déjà via ROME ;
    # on rejoint EXACTEMENT ce canonical (même chaîne) pour ajouter le seul
    # alias manquant, plutôt que de créer un canonical rival avec une
    # apostrophe droite.
    "Gestion d’actifs": ["gestionnaire de portefeuille"],
    # Idem pour "Finance d'entreprise" (apostrophe droite, déjà via ROME).
    "Finance d'entreprise": ["corporate finance"],
    "Capital investissement": ["capital investissement", "private equity", "capital developpement"],
    "Bâle III": ["bale 3", "bale iii", "basel iii"],
    "Solvabilité II": ["solvabilite 2", "solvabilite ii", "solvency ii"],
    # "KYC" existe déjà (ROME) ; on n'y touche pas et on crée seulement le
    # volet AML, non couvert.
    "Lutte anti-blanchiment (AML)": ["aml", "anti money laundering", "lutte anti-blanchiment"],
    "Crédit bancaire": ["credit bancaire", "analyse credit", "risque de credit", "octroi de credit"],
    "Middle Office": ["middle office"],
    "Back Office bancaire": ["back office bancaire", "back office titres"],
    "Front Office": ["front office"],
    "Valorisation d'entreprise": ["valorisation d entreprise", "evaluation d entreprise", "dcf valorisation"],
    "Modélisation financière": ["modelisation financiere", "financial modeling", "excel financier"],
    "Bloomberg Terminal": ["bloomberg terminal"],
    "Reuters Eikon": ["reuters eikon", "refinitiv eikon"],
    "Microfinance": ["microfinance", "institution de microfinance"],
    "Financement de projet": ["financement de projet", "project finance"],
    "Titrisation": ["titrisation", "securitization"],
    "Marchés obligataires": ["marches obligataires", "marche obligataire", "bond market"],
    "Produits dérivés": ["produits derives", "options et futures"],
    "Change (Forex)": ["forex", "marche des changes", "trading de devises"],
    "SWIFT (messagerie bancaire)": ["message swift", "systeme swift", "swift banking"],

    # ── RESSOURCES HUMAINES ────────────────────────────────────────────────
    "Recrutement": ["recrutement", "recruitment", "sourcing", "talent acquisition", "chasse de tetes", "recruteur"],
    "GPEC": ["gpec", "gepp", "gestion des emplois et competences", "gestion previsionnelle des emplois"],
    "SIRH": ["sirh", "hris", "workday", "oracle hrm", "sap hr", "systeme rh", "success factors"],
    "Droit du travail": ["droit du travail", "droit social", "droit du travail et de l emploi", "code du travail"],
    "Gestion des talents": ["gestion des talents", "talent management", "developpement des talents", "peoples review"],
    "Administration du personnel": ["administration du personnel", "administration rh", "gestion administrative rh"],
    "Relations sociales": ["relations sociales", "negociation syndicale", "dialogue social", "cse", "irp"],
    "Formation professionnelle": ["formation professionnelle", "plan de formation", "cpf", "plan de developpement des competences"],
    "Onboarding": ["onboarding", "accueil des nouveaux collaborateurs"],
    "Qualité de vie au travail": ["qvt", "bien etre au travail", "qualite de vie au travail", "rse", "qualite de vie"],
    "Gestion des conflits": ["gestion des conflits", "mediation", "resolution de conflits"],

    # ── RH (COMPLÉMENT 2026-09-17) ───────────────────────────────────────
    "Marque employeur": ["marque employeur", "employer branding"],
    "HRBP (HR Business Partner)": ["hrbp", "hr business partner", "rh de proximite"],
    "Mobilité interne": ["mobilite interne", "gestion de carriere"],
    "Entretien annuel": ["entretien annuel", "entretien d evaluation", "entretien professionnel"],
    "Diversité et inclusion": ["diversite et inclusion", "politique handicap en entreprise"],
    "Rémunération et avantages sociaux": ["remuneration et avantages sociaux", "compensation and benefits"],
    "Digitalisation RH": ["digitalisation rh", "digital hr"],
    "Entretien de recrutement": ["entretien de recrutement", "entretien d embauche"],
    "LinkedIn Recruiter": ["linkedin recruiter"],
    "ATS (Applicant Tracking System)": ["ats recrutement", "applicant tracking system", "logiciel de recrutement"],
    "Bilan de compétences": ["bilan de competences", "bilan professionnel"],

    # ── DROIT & JURIDIQUE ─────────────────────────────────────────────────
    "Droit des contrats": ["droit des contrats", "contract law", "redaction de contrats", "droit contractuel"],
    "Droit des affaires": ["droit des affaires", "business law", "droit commercial", "droit des societes"],
    "Propriété intellectuelle": ["propriete intellectuelle", "pi", "brevets", "marques", "droits d auteur", "pi"],
    "Droit public": ["droit public", "droit administratif", "droit constitutionnel", "droit de la commande publique"],
    "Compliance": ["compliance", "conformite", "conformite reglementaire", "projet reglementaire", "rgpd", "gdpr", "lcb ft"],
    "Contentieux": ["contentieux", "procedure judiciaire", "litige", "plaidoirie"],
    "Droit pénal": ["droit penal", "droit criminel", "procedure penale"],
    "Droit immobilier": ["droit immobilier", "droit de l urbanisme", "droit de la construction"],

    # ── LÉGAL (COMPLÉMENT 2026-09-17) ────────────────────────────────────
    "Droit international": ["droit international", "droit international prive", "droit international public"],
    # Bare "arbitrage" exclu : mot français courant signifiant aussi
    # "compromis/choix" hors contexte juridique (ex: "faire un arbitrage
    # entre deux options").
    "Arbitrage juridique": ["arbitrage juridique", "arbitrage commercial", "procedure d arbitrage"],
    "Notariat": ["notariat", "notaire", "acte notarie"],
    "Rédaction juridique": ["redaction juridique", "legal drafting", "redaction d actes"],
    "Veille juridique": ["veille juridique", "legal watch"],
    "Droit de la concurrence": ["droit de la concurrence", "droit antitrust"],
    "Droit bancaire et financier": ["droit bancaire", "droit financier"],
    "Legal Tech": ["legal tech", "legaltech"],
    "Juriste d'entreprise": ["juriste d entreprise", "in-house counsel", "corporate counsel"],

    # ── ASSURANCE, RISQUE & CONFORMITÉ ──────────────────────────────────────
    "IARD": ["iard"],
    # Bare "assurance" exclu : signifie aussi "confiance" en français courant
    # ("avoir de l assurance") et déjà couvert séparément par "assurance
    # qualite logicielle" -- même classe de faux positif que "recette"/"sas"
    # nus. Seules les expressions qualifiées ci-dessous sont sans ambiguïté ;
    # une mention nue d'"Assurance" reste exploitable via les mots-clés
    # prioritaires d'une offre (voir priority_keyword_component).
    "Assurance": ["secteur de l assurance", "compagnie d assurance", "assureur",
                  "assurance dommages", "assurance vie", "assurance iard"],
    "Gestion des sinistres": ["gestion des sinistres", "gestion de sinistre", "sinistres",
                              "declaration de sinistre", "indemnisation",
                              "sinistralite", "cycle de vie d un sinistre"],
    "Gestion des risques": ["gestion des risques", "gestion du risque", "analyse des risques",
                            "cartographie des risques", "indicateurs de risques", "risk management",
                            "risques it", "gestion des risques it"],
    "GRC (gouvernance, risques, conformité)": ["grc", "governance risk compliance",
                                               "gouvernance risques conformite"],
    "Lignes de défense (LOD)": ["lod1", "lod2", "lod3", "ligne de defense", "lignes de defense",
                                "line of defense", "1st line of defense", "2nd line of defense",
                                "3lod"],
    "NIST": ["nist", "nist framework", "nist csf"],
    # "Banque"/"Finance" volontairement PAS ajoutés comme mots de secteur
    # nus : un secteur mentionné dans un CV/offre n'est pas en soi une
    # compétence (même risque que "Grande distribution" ci-dessous). Un
    # recruteur qui veut le secteur d'une offre comme exigence peut toujours
    # le faire via les mots-clés prioritaires de CETTE offre.
    "Analyse des besoins": ["analyse des besoins", "besoins metiers", "recueil des besoins",
                            "expression de besoin", "expression des besoins"],
    "Outils bureautiques": ["outils bureautiques", "pack office", "suite office",
                            "microsoft office", "bureautique"],
    # "RUN" et "TRM" nus volontairement exclus : trop génériques/ambigus
    # pour un dictionnaire global (même raisonnement que "recette" plus
    # haut). Exploitables par offre via les mots-clés prioritaires.

    # ── LOGISTIQUE & SUPPLY CHAIN ──────────────────────────────────────────
    "Supply Chain": ["supply chain", "chaine d approvisionnement", "chaine logistique", "supply chain management"],
    "Gestion des stocks": ["gestion des stocks", "stock management", "inventaire", "gestion d entrepot", "gestion de stocks"],
    "Transport": ["logistique transport", "gestion du transport", "affretement", "expedition", "gestion des transports"],
    "Douane": ["douane", "transit douanier", "dedouanement", "incoterms", "transit"],
    "WMS": ["wms", "warehouse management system", "gestion entrepot", "manhattan", "reflex"],
    "ERP Logistique": ["sap mm", "sap sd", "oracle scm", "erp logistique", "sap wm"],
    "Approvisionnement": ["approvisionnement", "achats", "procurement", "purchasing", "acheteur"],
    "Planification logistique": ["planification logistique", "s&op", "sales and operations planning", "mrp"],
    "Distribution": ["reseau de distribution", "logistique du dernier km", "livraison last mile"],
    "Lean": ["lean", "lean management", "lean manufacturing", "kaizen"],
    "Six Sigma": ["six sigma", "6 sigma", "6sigma", "black belt", "green belt", "dmaic"],
    "Qualité": ["management de la qualite", "iso 9001", "certification qualite", "demarche qualite", "smed"],

    # ── LOGISTIQUE (COMPLÉMENT 2026-09-17) ───────────────────────────────
    "Gestion de flotte": ["gestion de flotte", "fleet management", "gestionnaire de flotte"],
    "Transport routier": ["transport routier", "affretement routier"],
    "Transport maritime": ["transport maritime", "fret maritime", "shipping maritime"],
    "Transport aérien": ["transport aerien", "fret aerien", "air freight"],
    "Logistique internationale": ["logistique internationale", "chaine logistique internationale"],
    "Cross-docking": ["cross-docking", "cross docking"],
    "Gestion des flux": ["gestion des flux", "flux tendus", "juste a temps", "just in time"],
    "Préparation de commandes": ["preparation de commandes", "picking entrepot", "order picking"],
    "Traçabilité logistique": ["tracabilite logistique", "suivi de tracabilite"],
    "Logistique inverse": ["reverse logistics", "logistique inverse", "gestion des retours"],
    "CACES (chariot élévateur)": ["caces", "chariot elevateur", "conduite de chariot"],
    "Transitaire": ["transitaire", "commissionnaire de transport"],

    # ── SANTÉ & MÉDICAL ───────────────────────────────────────────────────
    # "ide" (Infirmier Diplômé d'État) volontairement PAS un alias nu : bug
    # réel trouvé par AI Real-Time en validant leur import O*NET
    # (2026-09-17) -- collision avec l'abréviation tech omniprésente IDE
    # (Integrated Development Environment, "Eclipse IDE", "un bon IDE"...),
    # que cette taxonomie couvre désormais largement. Un vrai CV d'infirmier
    # dit "infirmier"/"soins infirmiers" ou épelle "IDE" avec du contexte
    # autour bien plus souvent que la forme nue à 3 lettres seule.
    "Soins infirmiers": ["soins infirmiers", "infirmier", "nursing", "soins aux patients"],
    "Pharmacologie": ["pharmacologie", "pharmacie", "medicaments", "dispensation", "pharmacien"],
    "Soins d'urgence": ["urgences", "soins d urgence", "smur", "reanimation", "samu"],
    "Bloc opératoire": ["bloc operatoire", "chirurgie", "instrumentiste", "aide soignant", "ibode"],
    "Médecine générale": ["medecine generale", "omnipraticien", "consultation medicale", "medecin"],
    "Radiologie": ["radiologie", "imagerie medicale", "echographie", "scanner", "irm", "manipulateur"],
    "Kinésithérapie": ["kinesitherapie", "kinesitherapeute", "reeducation", "physiotherapie", "mkde"],
    "Psychologie": ["psychologie", "psychologue", "psychotherapie", "counseling", "therapie"],
    "Nutrition": ["nutrition", "dietetique", "dieteticien", "dietetiste"],
    "Hygiène hospitalière": ["hygiene hospitaliere", "bio-nettoyage", "asepsie", "sterilisation"],

    # ── SANTÉ (COMPLÉMENT 2026-09-17) ────────────────────────────────────
    # "Odontologie"/"Orthodontie" existent déjà (ROME/ESCO) ; on y ajoute
    # seulement les alias manquants plutôt que de créer un "Dentisterie"
    # rival.
    "Odontologie": ["chirurgien-dentiste", "soins dentaires"],
    "Médecine vétérinaire": ["medecine veterinaire", "veterinaire", "soins animaliers"],
    "Analyses de laboratoire": ["analyses de laboratoire", "laboratoire d analyses medicales"],
    # "Santé publique"/"Gériatrie" ci-dessous rejoignent des canonicals ROME
    # déjà identiques (même chaîne) ; "epidemiologie"/"gerontologie" déjà
    # couverts séparément donc omis ici.
    "Santé publique": ["promotion de la sante"],
    "Gestion hospitalière": ["gestion hospitaliere", "administration hospitaliere"],
    "Aide à domicile": ["aide a domicile", "auxiliaire de vie", "aide medico-psychologique"],
    "Dispositifs médicaux": ["dispositifs medicaux", "materiel medical"],
    "Télémédecine": ["telemedecine", "telesante", "teleconsultation"],
    "Gériatrie": ["soins aux personnes agees", "ehpad"],
    "Pédiatrie": ["pediatrie", "soins pediatriques"],
    "Sécurité sociale": ["securite sociale", "assurance maladie", "cpam", "protection sociale"],
    "Orthophonie": ["orthophonie", "orthophoniste", "reeducation du langage"],
    "Ergothérapie": ["ergotherapie", "ergotherapeute"],
    "Sage-femme": ["sage-femme", "maieutique", "obstetrique"],

    # ── BTP & CONSTRUCTION ────────────────────────────────────────────────
    "AutoCAD": ["autocad", "cao", "dessin assiste par ordinateur", "dessin technique", "catia", "solidworks"],
    "BIM": ["bim", "building information modeling", "revit", "archicad", "bim manager"],
    "Génie civil": ["genie civil", "civil engineering", "beton arme", "gros oeuvre"],
    "Conduite de travaux": ["conduite de travaux", "chef de chantier", "conducteur de travaux"],
    "Maîtrise d'ouvrage": ["maitrise d ouvrage", "moa", "maitre d ouvrage", "amoa"],
    "Maîtrise d'œuvre": ["maitrise d oeuvre", "moe", "maitre d oeuvre"],
    "Électricité bâtiment": ["electrotechnique", "courants forts", "courants faibles", "cfao", "electricite batiment"],
    "Plomberie CVC": ["plomberie", "sanitaire", "genie climatique", "cvc", "hvac"],
    "Métré": ["metre", "metreur", "estimatif", "quantitatif", "bordereau"],
    "QSE": ["qse", "hse", "qhse", "securite chantier", "prevention des risques", "document unique"],

    # ── CONSTRUCTION (COMPLÉMENT 2026-09-17) ─────────────────────────────
    # "Second oeuvre" et "Economie de la construction" existent déjà
    # (ROME) sous une orthographe légèrement différente (oe vs œ, sans
    # accent vs avec) mais un fold identique ; pas de nouvel alias à
    # ajouter, donc pas d'entrée ici pour éviter un canonical rival.
    "VRD (Voirie et Réseaux Divers)": ["vrd", "voirie et reseaux divers"],
    "Permis de construire": ["permis de construire", "dossier de permis", "autorisation d urbanisme"],
    "RE2020 / Réglementation thermique": ["re2020", "rt2012", "reglementation thermique batiment"],
    "Matériaux de construction": ["materiaux de construction", "materiaux batiment"],
    "Engins de chantier": ["engins de chantier", "conduite d engins", "pelleteuse"],
    "Diagnostic immobilier": ["diagnostic immobilier", "dpe immobilier"],
    "Economiste de la construction": ["economiste de la construction"],
    "Coordination SPS": ["coordination sps", "coordinateur sps"],
    "Topographie": ["topographie", "geometre", "leve topographique"],
    "Urbanisme": ["urbanisme", "amenagement du territoire", "plan local d urbanisme"],

    # ── ÉDUCATION & FORMATION ─────────────────────────────────────────────
    "Pédagogie": ["pedagogie", "pedagogy", "methodes pedagogiques", "ingenierie pedagogique"],
    "E-learning": ["e-learning", "formation en ligne", "enseignement a distance", "mooc", "lms"],
    "Conception pédagogique": ["conception pedagogique", "instructional design", "design pedagogique", "ingenierie de formation"],
    "Tutorat": ["tutorat", "tutoring", "soutien scolaire", "accompagnement scolaire", "tuteur"],
    "Mathématiques": ["mathematiques", "maths", "mathematics", "statistiques appliquees"],

    # ── ÉDUCATION (COMPLÉMENT 2026-09-17) ────────────────────────────────
    "Andragogie": ["andragogie", "adult learning"],
    "Différenciation pédagogique": ["differenciation pedagogique", "pedagogie differenciee"],
    "Classe inversée": ["classe inversee", "flipped classroom"],
    "Évaluation des apprentissages": ["evaluation des apprentissages", "evaluation formative", "evaluation sommative"],
    "Moodle": ["moodle"],
    "Google Classroom": ["google classroom"],
    "Canvas LMS": ["canvas lms"],
    "Blackboard": ["blackboard lms"],
    "Formateur d'adultes": ["formateur d adultes", "formateur professionnel"],
    "Orientation scolaire et professionnelle": ["orientation scolaire", "orientation professionnelle", "conseiller d orientation"],
    "Direction d'établissement scolaire": ["direction d etablissement", "chef d etablissement", "proviseur", "principal de college"],
    "Vie scolaire": ["vie scolaire", "conseiller principal d education", "cpe"],
    "FLE (Français Langue Étrangère)": ["fle", "francais langue etrangere"],
    "Didactique": ["didactique", "didactique des disciplines"],
    "Recherche académique": ["recherche academique", "publication scientifique", "travaux de recherche", "these de doctorat"],
    "Rédaction de mémoire": ["redaction de memoire", "memoire de recherche"],
    "Bibliothéconomie": ["bibliotheconomie", "documentaliste", "sciences de l information"],
    "Petite enfance": ["petite enfance", "eveil de l enfant", "auxiliaire de puericulture"],
    "Apprentissage par projet": ["apprentissage par projet", "project-based learning", "pedagogie de projet"],
    "Gamification pédagogique": ["gamification pedagogique", "ludopedagogie", "serious game"],

    # ── COMPÉTENCES TRANSVERSALES ──────────────────────────────────────────
    # Exclues du calcul de couverture technique (voir SOFT_SKILL_CANONICALS
    # ci-dessous) -- des traits comportementaux mélangés aux compétences
    # techniques diluent le signal de correspondance métier.
    "Travail en équipe": ["travail en equipe", "teamwork", "esprit d equipe", "collaboration", "team player"],
    "Autonomie": ["autonomie", "autonome", "self-management", "organisation personnelle", "independant"],
    "Rigueur": ["rigueur", "precision", "minutie", "attention aux details", "rigueur professionnelle"],
    "Adaptabilité": ["adaptabilite", "adaptable", "flexibilite", "polyvalence", "agilite d adaptation"],
    "Créativité": ["creativite", "creatif", "inventivite", "ideation"],
    "Organisation": ["organisation", "sens de l organisation", "organise", "structuration"],
    "Sens du service": ["sens du service", "orientation client", "service oriented"],
    "Esprit d'analyse": ["esprit d analyse", "analytical skills", "analyse", "sens analytique", "capacite d analyse"],
    "Force de proposition": ["force de proposition", "proactif", "proactivite", "initiative", "acteur du changement"],
    "Gestion du stress": ["gestion du stress", "resistance au stress", "sang-froid", "resilience"],
    "Permis B": ["permis b", "permis de conduire", "vehicule leger"],

    # ── GÉNÉRAL / TRANSVERSAL (COMPLÉMENT 2026-09-17) ────────────────────
    "Multilinguisme": ["multilinguisme", "bilingue", "trilingue", "multilingual"],
    # Bare "responsabilite" exclu : trop générique, collisionne avec les
    # en-têtes de section de CV ("Responsabilités : ...") sans indiquer une
    # compétence démontrée.
    "Sens des responsabilités": ["sens des responsabilites", "sens du devoir"],
    "Curiosité intellectuelle": ["curiosite intellectuelle", "curiosite professionnelle"],
    "Esprit critique": ["esprit critique", "pensee critique", "critical thinking"],
    "Capacité d'apprentissage": ["capacite d apprentissage", "apprentissage continu", "learning agility"],
    "Orientation résultats": ["orientation resultats", "orientation performance"],
    "Discrétion professionnelle": ["discretion professionnelle", "devoir de reserve"],
    "Empathie": ["empathie", "ecoute empathique"],
    # "Ethique professionnelle" (sans accent) existe déjà (ROME) sous ce
    # nom exact ; on y ajoute seulement les alias manquants.
    "Ethique professionnelle": ["deontologie professionnelle", "integrite professionnelle"],

    # ── COMPLÉMENT ISSU DE 67 OFFRES D'EMPLOI RÉELLES (2026-09-17) ──────
    # Extrait de mod326_js_job_jobs.json (export production, offres ESN
    # tech/finance/telecom réelles) par AI Real-Time. Deux volets : des
    # compétences totalement absentes de la taxonomie (nouveaux outils/
    # réglementations), et des compétences déjà reconnues via ROME/ESCO/
    # O*NET/e-CF mais promues ici dans le dictionnaire de confiance manuel.
    "FinOps": ["finops", "gouvernance financiere cloud"],
    "SEFAS HCS": ["sefas hcs", "suite sefas", "sefas v6"],
    "ATEM MDM": ["atem mdm", "outil atem"],
    "Nutanix": ["nutanix", "nutanix ahv", "cluster nutanix"],
    "Quarkus": ["quarkus"],
    "MicroStrategy": ["microstrategy", "micro strategy"],
    "XL Release / XL Deploy": ["xl release", "xl deploy", "xldeploy", "xlr", "xld"],
    "Xray (gestion de tests Jira)": ["jira xray", "xray test management"],
    "LPM (Loi de Programmation Militaire)": ["lpm"],
    "DSP2 (PSD2)": ["dsp2", "psd2", "payment services directive"],
    "Planon": ["planon", "planon software"],
    "Dynatrace": ["dynatrace"],
    # Note : "MCO" est aussi l'acronyme hospitalier "Médecine-Chirurgie-
    # Obstétrique" (service/pôle MCO) -- collision mineure acceptée (le
    # domaine santé ne représente que 0.5% du corpus de validation d'AI
    # Real-Time).
    "MCO (Maintien en Condition Opérationnelle)": ["mco", "maintien en condition operationnelle"],
    "IMS DL/1": ["dl1", "ims dl/1", "ims db"],
    "Amazon EC2": ["amazon ec2"],
    "Amélioration des processus": ["amelioration des processus"],
    "Analysis Services": ["analysis services"],
    "Anglais professionnel": ["anglais professionnel"],
    "Apache": ["apache"],
    "Apache Cassandra": ["apache cassandra"],
    "Apache Hadoop": ["apache hadoop"],
    "Apache Hive": ["apache hive"],
    "Apache Spark": ["apache spark"],
    "Big Data": ["big data"],
    "Conception des applications": ["conception des applications"],
    "Concepts des télécommunications": ["concepts des telecommunications"],
    "Documentation technique": ["documentation technique"],
    "Données non structurées": ["donnees non structurees"],
    "Gestion de bases de données": ["gestion de bases de donnees"],
    "Gestion de projets": ["gestion de projets"],
    "Gestion des actifs": ["gestion des actifs"],
    "Gestion des coûts": ["gestion des couts"],
    "Gestion des incidents": ["gestion des incidents"],
    "Gestion des problèmes": ["gestion des problemes"],
    "Gestion des ressources": ["gestion des ressources"],
    "Gestion du changement": ["gestion du changement"],
    "Gestion financière": ["gestion financiere"],
    "Google Android": ["google android"],
    "Groovy": ["groovy"],
    "Hadoop": ["hadoop"],
    "Hibernate ORM": ["hibernate orm"],
    "IOS": ["ios"],
    "Intégration de systèmes": ["integration de systemes"],
    "MDX": ["mdx"],
    "Marketing numérique": ["marketing numerique"],
    "Micro-informatique": ["micro-informatique"],
    "Modèles de données": ["modeles de donnees"],
    "Modélisation orientée services": ["modelisation orientee services"],
    "Métrologie": ["metrologie"],
    "NoSQL": ["nosql"],
    "Normes de sécurité": ["normes de securite"],
    "OpenShift": ["openshift"],
    "Perl": ["perl"],
    "Portugais": ["portugais"],
    "Postman": ["postman"],
    "PowerShell": ["powershell"],
    "Procédures de sauvegarde des données": ["procedures de sauvegarde des donnees"],
    "Protection des données": ["protection des donnees"],
    "Routage": ["routage"],
    "Règles de sécurité": ["regles de securite"],
    "SharePoint": ["sharepoint"],
    "Spring Framework": ["spring framework"],
    "Stockage de données": ["stockage de donnees"],
    "Suivi de projet": ["suivi de projet"],
    "Sybase": ["sybase"],
    "Systèmes d'information": ["systemes d'information"],
    "Systèmes d’exploitation": ["systemes dexploitation"],
    "Sécurité des systèmes d'information": ["securite des systemes d'information"],
    "Techniques comptables": ["techniques comptables"],
    "Technologies de dématérialisation": ["technologies de dematerialisation"],
    "UNIX Shell": ["unix shell"],
    "Veille technologique": ["veille technologique"],
    "Windows Server": ["windows server"],
    "XML": ["xml"],
    "WildFly": ["jboss"],
    "Transact-SQL": ["transact sql"],
    "Base de données": ["entrepot de donnees"],

    # ── COMPLÉMENT ISSU DE 33 574 PROFILS CANDIDATS RÉELS (2026-09-17) ──
    # Extrait par AI Real-Time des champs "keywords"/"skills" de
    # mod326_js_job_resume.json (export production, mots-clés auto-déclarés
    # par les candidats). Promotions depuis ROME/ESCO/O*NET/e-CF vers le
    # dictionnaire de confiance manuel (mêmes noms canoniques exacts, pas
    # de canonical rival créé). Mots génériques à risque (Architecture/
    # Cycle/marketing/Logistique/Statistiques/Francais/Technologie/
    # Ecosystemes/Prevention) délibérément laissés hors de ce niveau, même
    # piège que Chef/SAS trouvé plus tôt.
    "Alteryx": ["alteryx"],
    "Amazon DynamoDB": ["amazon dynamodb"],
    "Amazon Redshift": ["amazon redshift"],
    "Apache Airflow": ["apache airflow"],
    "Apache Tomcat": ["apache tomcat"],
    "Apple macOS": ["apple macos"],
    "Application web": ["application web"],
    "ArcGIS": ["arcgis"],
    "Asset management": ["asset management"],
    "Automatisme": ["automatisme"],
    "BGP": ["bgp"],
    "Cisco Webex": ["cisco webex"],
    "Cobol": ["cobol"],
    "Cognos": ["cognos"],
    "Cryptomonnaie": ["cryptomonnaie"],
    "Drupal": ["drupal"],
    "Développement de logiciels": ["developpement de logiciels"],
    "E-commerce": ["e-commerce"],
    "Electromagnétisme": ["electromagnetisme"],
    "Electronique": ["electronique"],
    "Fortran": ["fortran"],
    "GRH": ["grh"],
    "Gestion de crise": ["gestion de crise"],
    "Gestion des services informatiques": ["gestion des services informatiques"],
    "Graphiques animés": ["graphiques animes"],
    "Génie logiciel": ["genie logiciel"],
    "Infographie": ["infographie"],
    "Informatique industrielle": ["informatique industrielle"],
    "Intelligence artificielle": ["intelligence artificielle"],
    "JQuery": ["jquery"],
    "Knowledge Management": ["knowledge management"],
    "MATLAB": ["matlab"],
    "Maintenance prédictive": ["maintenance predictive"],
    "Maltego": ["maltego"],
    "Marketing relationnel": ["marketing relationnel"],
    "Maîtrise de la langue française": ["maitrise de la langue francaise"],
    "Microprogramme": ["microprogramme"],
    "Microsoft Active Directory": ["microsoft active directory"],
    "Microsoft Outlook": ["microsoft outlook"],
    "Microsoft Teams": ["microsoft teams"],
    "Modélisation orientée objet": ["modelisation orientee objet"],
    "Monétique": ["monetique"],
    "Nessus": ["nessus"],
    "Oracle Cloud": ["oracle cloud"],
    "Power Platform": ["power platform"],
    "Puppet": ["puppet"],
    "RACI": ["raci"],
    "Red Hat Enterprise Linux": ["red hat enterprise linux"],
    "Responsive design": ["responsive design"],
    "Risques technologiques": ["risques technologiques"],
    "Rédaction de cahier des charges": ["redaction de cahier des charges"],
    "Rétro-ingénierie": ["retro-ingenierie"],
    "SAP Concur": ["sap concur"],
    "Script Shell": ["script shell"],
    "Service clients": ["service clients"],
    "Slack": ["slack"],
    "SoapUI": ["soapui"],
    "Splunk": ["splunk"],
    "Systèmes embarqués": ["systemes embarques"],
    "Sécurité des applications": ["securite des applications"],
    "Sécurité des réseaux": ["securite des reseaux"],
    "TensorFlow": ["tensorflow"],
    "Tests fonctionnels": ["tests fonctionnels"],
    "Tests utilisateurs": ["tests utilisateurs"],
    "Traitement du signal": ["traitement du signal"],
    "Wireshark": ["wireshark"],

    # ── AJOUTS PROPRES À KEONI (sans équivalent chez AI Real-Time) ─────────
    # jQuery a existé ici comme ajout Keoni jusqu'au portage de 2561ad5, qui
    # introduit "JQuery" (même alias "jquery") -- retiré pour éviter deux
    # canonicaux distincts (le second silencieusement mort, jamais
    # atteignable) sur la même compétence.
    "Développeur Web": ["dev web", "developpeur web", "web developer"],
}

# Traits comportementaux (bloc "COMPÉTENCES TRANSVERSALES" ci-dessus),
# distincts du vocabulaire générique ci-dessous : jamais comptés comme
# compétence technique (voir find_skills()). Portage verbatim de
# SOFT_SKILL_CANONICALS côté AI Real-Time.
SOFT_SKILL_CANONICALS: frozenset[str] = frozenset({
    "Travail en équipe",
    "Autonomie",
    "Rigueur",
    "Adaptabilité",
    "Créativité",
    "Organisation",
    "Sens du service",
    "Esprit d'analyse",
    "Force de proposition",
    "Gestion du stress",
    "Permis B",
})

# Libellés canoniques (du dictionnaire ci-dessus OU du référentiel ROME)
# qui sont du vocabulaire professionnel générique plutôt que des
# compétences concrètes — une offre qui dit juste "bonne communication" ou
# "sens du service" ne devrait pas compter comme une compétence technique
# au même titre que "Docker" ou "SQL". Portage verbatim de
# _GENERIC_SKILL_CANONICALS côté AI Real-Time (a4f576f/61886a9), plus
# "Grande distribution" -- un ajout à nous, absent de leur liste (voir
# son propre commentaire ci-dessous pour le cas réel qui l'a motivé).
_GENERIC_SKILL_CANONICALS: frozenset[str] = frozenset({
    "Communication",
    "Service client",
    "Contrôle qualité",
    "Mathématiques",
    "Outils bureautiques",
    "Qualité",
    "Résolution de problèmes",
    "Présentation",
    "Ecoute active",
    "Gestion du temps",
    # "Grande distribution" est un ajout à NOUS, pas un portage : absente de
    # la liste d'AI Real-Time (leur commentaire dit explicitement que leur
    # import ROME 8500+ entrées n'a pas été audité en entier, celle-ci n'a
    # simplement jamais été rencontrée chez eux). Trouvée en auditant Keoni
    # sur un échantillon d'offres réelles (2026-09-15) : 4 offres sur 5
    # testées partagent le même paragraphe passe-partout d'ESN ("nous
    # accompagnons nos clients de l'industrie, banque & assurance, grande
    # distribution & e-commerce...") en tête ou pied de texte — ce n'est
    # jamais une exigence du poste, juste la liste des secteurs clients de
    # l'agence, et avec seulement 3-4 compétences détectées par offre en
    # moyenne, ce faux positif à lui seul pesait ~25 points de couverture
    # sur un candidat par ailleurs bien aligné (cas réel audité : 45.5 au
    # lieu des ~65+ attendus).
    "Grande distribution",
})

# Ensemble complet exclu du calcul de couverture technique (les deux
# raisons sont distinctes -- trait comportemental vs vocabulaire générique
# -- mais le traitement dans find_skills() est identique).
_EXCLUDED_FROM_HARD_SKILLS: frozenset[str] = SOFT_SKILL_CANONICALS | _GENERIC_SKILL_CANONICALS


@lru_cache(maxsize=1)
def _esco_skills() -> Dict[str, List[str]]:
    """Vocabulaire ESCO v1.2.1 (classification française), filtré et
    pré-généré par AI Real-Time hors-ligne : lignes skillType=="knowledge"
    avec un libellé préféré d'au plus 3 mots (~1916 compétences
    canoniques, 3069 alias). Portage direct de leur `_esco_skills()`
    (8d20172) -- même fichier, copié tel quel (esco_skills_data.json).

    Contrairement à ROME, les libellés ESCO sont surtout des phrases-tâches
    complètes ("gérer des demandes d'indemnisation"), pas des termes courts
    façon mot-clé -- d'où le filtre par nombre de mots et le statut de
    couche encore moins prioritaire que ROME (voir _load_lookup()).
    Fichier manquant/corrompu ne fait pas échouer le module.
    """
    if not _ESCO_SKILLS_PATH.is_file():
        return {}
    try:
        return json.loads(_ESCO_SKILLS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


@lru_cache(maxsize=1)
def _onet_skills() -> Dict[str, List[str]]:
    """Outils/technologies nommés d'O*NET 31.0 (Hot Technology=="Y",
    la curation officielle des outils marquants/tendance), déjà
    filtrés et hand-mappés par AI Real-Time (~100 entrées, b16d32e).
    Ce sont des noms de produit/marque (Kubernetes, Snowflake, Terraform...),
    pas des descriptions de compétence traduites -- ils matchent donc
    aussi bien en texte français que la source anglophone (US Dept. of
    Labor) ne le laisserait supposer. Couche la moins prioritaire avec
    e-CF (voir _load_lookup()). Fichier manquant/corrompu ne fait pas
    échouer le module.
    """
    if not _ONET_SKILLS_PATH.is_file():
        return {}
    try:
        return json.loads(_ONET_SKILLS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


@lru_cache(maxsize=1)
def _ecf_skills() -> Dict[str, List[str]]:
    """Les 40 compétences ICT du référentiel européen e-Competence
    Framework (e-CF) 3.0 (CWA 16234-1:2014, CEN), édition française --
    un standard UE fixe et restreint, pas un import en vrac. Déjà
    hand-review par AI Real-Time (b16d32e) : "Innovation" et "Tests"
    exclus (trop génériques seuls). Couche la moins prioritaire avec
    O*NET. Fichier manquant/corrompu ne fait pas échouer le module.
    """
    if not _ECF_SKILLS_PATH.is_file():
        return {}
    try:
        return json.loads(_ECF_SKILLS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


@lru_cache(maxsize=1)
def _load_lookup() -> Dict[str, str]:
    """alias replié -> libellé canonique.

    _TECH_SKILLS est chargé en premier et prioritaire (via setdefault, ROME
    ne peut jamais l'écraser) ; ROME ne fait que combler les trous. Le
    fichier ROME manquant/corrompu ne fait pas échouer le module.

    N'indexe que les alias explicitement déclarés, jamais le nom canonique
    lui-même : AI Real-Time indexait aussi le canonique comme alias
    implicite, et sur ce même fichier ROME (8508 entrées, souvent nommées
    d'un simple mot métier générique : "Distribution", "Qualité",
    "Management"...) ça faisait matcher n'importe quelle occurrence isolée
    de ce mot, sans rapport avec la compétence (corrigé chez eux en
    2d670be). Les alias explicites de rome_skills_data.json couvrent déjà
    la forme repliée du canonique quand c'est pertinent.

    Un alias contenant "/" est aussi indexé sous sa forme espacée
    ("ci/cd" -> aussi "ci cd") : le tokenizer de find_skills() traite "/"
    comme un séparateur (voir _TOKEN_RE), donc un texte source "CI/CD" se
    tokenize en deux mots "ci","cd" et ne matcherait jamais la clé "ci/cd"
    telle quelle sans cette indexation miroir. Même mécanisme que
    _build_lookup() côté AI Real-Time.
    """
    lookup: Dict[str, str] = {}

    for canonical, aliases in _TECH_SKILLS.items():
        for alias in aliases:
            key = _fold(alias)
            if len(key) <= 1:
                continue
            lookup.setdefault(key, canonical)
            if "/" in key:
                space_key = key.replace("/", " ")
                if space_key:
                    lookup.setdefault(space_key, canonical)

    if _ROME_SKILLS_PATH.is_file():
        try:
            raw = json.loads(_ROME_SKILLS_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = {}

        for canonical, aliases in raw.items():
            if not isinstance(aliases, list):
                continue
            for alias in aliases:
                key = _fold(str(alias))
                if len(key) <= 1 or key in _ROME_ALIAS_STOPWORDS:
                    continue
                lookup.setdefault(key, canonical)

    # Couche de repli suivante, moins prioritaire que ROME : vocabulaire
    # ESCO en vrac, même règle "ne comble que les trous" -- vérifiée après
    # ROME pour qu'un alias ROME l'emporte toujours en cas de conflit (les
    # libellés courts façon mot-clé de ROME collent mieux au matching par
    # sous-chaîne exacte de ce module -- voir _esco_skills()).
    for canonical, aliases in _esco_skills().items():
        for alias in aliases:
            key = _fold(alias)
            if key and len(key) >= 2 and key not in lookup:
                lookup[key] = canonical

    # Couches de repli les moins prioritaires : outils O*NET "Hot
    # Technology" puis les 40 compétences du référentiel e-CF -- vérifiées
    # en dernier, rien au-dessus n'est jamais masqué.
    for canonical, aliases in _onet_skills().items():
        for alias in aliases:
            key = _fold(alias)
            if key and len(key) >= 2 and key not in lookup:
                lookup[key] = canonical

    for canonical, aliases in _ecf_skills().items():
        for alias in aliases:
            key = _fold(alias)
            if key and len(key) >= 2 and key not in lookup:
                lookup[key] = canonical

    return lookup


# Alias ROME faux positifs sur des mots-outils français quasi omniprésents
# ("c'était" tokenize en "c" nu, "son équipe" en "son" nu) -- portage de
# _ROME_ALIAS_STOPWORDS côté AI Real-Time. "projet social" ajouté au
# portage 2026-09-17 (2561ad5, trouvé sur 33 574 profils réels) : sens
# RH/relations sociales voulu par ROME, mais collision avec le titre de CV
# très courant "Chef de projet social media".
_ROME_ALIAS_STOPWORDS: frozenset[str] = frozenset({"son", "projet social"})


def _fold(value: str) -> str:
    nfkd = unicodedata.normalize("NFKD", value)
    return nfkd.encode("ascii", "ignore").decode("ascii").lower()


def normalize_skill(term: str) -> str | None:
    """Libellé canonique pour un terme isolé, ou None si inconnu.

    .strip() manquant par rapport à la version d'AI Real-Time -- invisible
    tant que les seuls appelants passaient des termes déjà propres, mais
    normalize_priority_keyword() (scoring.py) appelle ceci sur des
    fragments issus d'un raw_term.split("/") qui gardent l'espace attenant
    ("gestion des sinistres / Sinistre".split("/") -> "gestion des
    sinistres " avec espace final), jamais reconnu sans ce strip() -- trouvé
    en auditant Keoni sur un échantillon d'offres réelles (2026-09-15).
    """
    return _load_lookup().get(_fold(term.strip()))


def find_skills(text: str, max_results: int = 50) -> List[str]:
    """Compétences détectées dans un texte libre (offre ou CV), dédupliquées,
    dans l'ordre de première apparition. Scan glouton du plus long n-gramme au
    plus court pour éviter qu'un match partiel ne casse un libellé multi-mots.
    Les traits comportementaux (SOFT_SKILL_CANONICALS) et le vocabulaire
    générique (_GENERIC_SKILL_CANONICALS) sont détectés (les tokens sont
    consommés) mais jamais renvoyés comme compétence.
    """
    lookup = _load_lookup()
    if not lookup or not text:
        return []

    raw_tokens = _TOKEN_RE.findall(text.lower())
    # Un mot en fin de phrase garde son "." ("Docker.") : on l'enlève en
    # bordure sans toucher aux tokens qui en ont légitimement un ("node.js").
    tokens = [tok for tok in (t.strip(".,;:!?") for t in raw_tokens) if tok]
    if not tokens:
        return []

    found: List[str] = []
    seen: set[str] = set()
    i = 0
    n = len(tokens)

    while i < n:
        matched = False
        for size in range(min(_MAX_NGRAM, n - i), 0, -1):
            candidate = " ".join(tokens[i : i + size])
            canonical = lookup.get(_fold(candidate))
            if canonical:
                # Vocabulaire générique/traits comportementaux (voir
                # _EXCLUDED_FROM_HARD_SKILLS) : les tokens sont bien
                # consommés (pas de rescan à une taille plus courte), mais
                # le "match" n'est jamais ajouté aux compétences détectées.
                if canonical not in _EXCLUDED_FROM_HARD_SKILLS and canonical not in seen:
                    seen.add(canonical)
                    found.append(canonical)
                    if len(found) >= max_results:
                        return found
                i += size
                matched = True
                break
        if not matched:
            i += 1

    return found
