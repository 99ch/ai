"""Normalisation de compétences, sur le même principe à deux couches qu'AI
Real-Time : un dictionnaire de synonymes métier fait main (prioritaire),
complété par le référentiel ROME (France Travail) comme couche de repli
plus large.

_TECH_SKILLS ci-dessous est un portage quasi intégral du `_SKILLS` d'AI
Real-Time (backend/app/services/taxonomy.py, 2026-09-15) -- pas leur
couche ESCO/FAISS (esco_taxonomy.py), qui reste hors scope (CSV à
télécharger manuellement derrière un CAPTCHA) ET qui, vérifié en lisant
leur code, n'alimente même pas leur moteur de scoring réel
(match_cv_to_job/matcher.py) : celui-ci passe par parser.py puis par CE
MÊME dictionnaire `_SKILLS`, qu'ESCO n'est branché que sur scoring_v2.py/
structured.py, explicitement qualifiés de "POC additif, pas encore
adopté" par leur propre docstring. Porter leur dictionnaire réel donne
donc la vraie parité de score visée, sans avoir besoin de l'infrastructure
FAISS/CSV qu'eux-mêmes ne consultent pas pour noter un candidat.

Trouvé en auditant Keoni sur un échantillon de CV/offres réels
(2026-09-15) : l'ancien dictionnaire, volontairement restreint au
développement web, ratait toute compétence des domaines gouvernance/
risque/conformité/assurance/RH/finance/juridique/logistique/santé/BTP —
exactement les domaines que ce portage couvre. Deux entrées propres à
Keoni sans équivalent chez AI Real-Time sont conservées en fin de
dictionnaire (jQuery, Développeur Web).

rome_skills_data.json est un export ouvert du référentiel ROME 4.0
("savoir"), scope "3DS MAX" -> ["3ds max"] : libellé canonique -> alias.
"""

from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Dict, List

_ROME_SKILLS_PATH = Path(__file__).with_name("data") / "rome_skills_data.json"
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

    # ── DROIT & JURIDIQUE ─────────────────────────────────────────────────
    "Droit des contrats": ["droit des contrats", "contract law", "redaction de contrats", "droit contractuel"],
    "Droit des affaires": ["droit des affaires", "business law", "droit commercial", "droit des societes"],
    "Propriété intellectuelle": ["propriete intellectuelle", "pi", "brevets", "marques", "droits d auteur", "pi"],
    "Droit public": ["droit public", "droit administratif", "droit constitutionnel", "droit de la commande publique"],
    "Compliance": ["compliance", "conformite", "conformite reglementaire", "projet reglementaire", "rgpd", "gdpr", "lcb ft"],
    "Contentieux": ["contentieux", "procedure judiciaire", "litige", "plaidoirie"],
    "Droit pénal": ["droit penal", "droit criminel", "procedure penale"],
    "Droit immobilier": ["droit immobilier", "droit de l urbanisme", "droit de la construction"],

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

    # ── SANTÉ & MÉDICAL ───────────────────────────────────────────────────
    "Soins infirmiers": ["soins infirmiers", "infirmier", "nursing", "soins aux patients", "ide"],
    "Pharmacologie": ["pharmacologie", "pharmacie", "medicaments", "dispensation", "pharmacien"],
    "Soins d'urgence": ["urgences", "soins d urgence", "smur", "reanimation", "samu"],
    "Bloc opératoire": ["bloc operatoire", "chirurgie", "instrumentiste", "aide soignant", "ibode"],
    "Médecine générale": ["medecine generale", "omnipraticien", "consultation medicale", "medecin"],
    "Radiologie": ["radiologie", "imagerie medicale", "echographie", "scanner", "irm", "manipulateur"],
    "Kinésithérapie": ["kinesitherapie", "kinesitherapeute", "reeducation", "physiotherapie", "mkde"],
    "Psychologie": ["psychologie", "psychologue", "psychotherapie", "counseling", "therapie"],
    "Nutrition": ["nutrition", "dietetique", "dieteticien", "dietetiste"],
    "Hygiène hospitalière": ["hygiene hospitaliere", "bio-nettoyage", "asepsie", "sterilisation"],

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

    # ── ÉDUCATION & FORMATION ─────────────────────────────────────────────
    "Pédagogie": ["pedagogie", "pedagogy", "methodes pedagogiques", "ingenierie pedagogique"],
    "E-learning": ["e-learning", "formation en ligne", "enseignement a distance", "mooc", "lms"],
    "Conception pédagogique": ["conception pedagogique", "instructional design", "design pedagogique", "ingenierie de formation"],
    "Tutorat": ["tutorat", "tutoring", "soutien scolaire", "accompagnement scolaire", "tuteur"],
    "Mathématiques": ["mathematiques", "maths", "mathematics", "statistiques appliquees"],

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

    # ── AJOUTS PROPRES À KEONI (sans équivalent chez AI Real-Time) ─────────
    "jQuery": ["jquery"],
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

    return lookup


# Alias ROME faux positifs sur des mots-outils français quasi omniprésents
# ("c'était" tokenize en "c" nu, "son équipe" en "son" nu) -- portage de
# _ROME_ALIAS_STOPWORDS côté AI Real-Time.
_ROME_ALIAS_STOPWORDS: frozenset[str] = frozenset({"son"})


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
