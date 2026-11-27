"""Generic tech-skills dictionary: canonical name -> regex. Public and profile-free.

Which of these skills you have lives in the PROFILE_SKILLS secret (or profile.local.json),
never in this repo.
"""
import re

_RAW = {
    # languages
    "Python": r"\bpython\b", "SQL": r"\bsql\b", "Java": r"\bjava\b(?!script)", "C++": r"c\+\+", "C": r"\bc\b(?![+#])(?=,|\s+(?:and|or)\b|/)",
    "C#": r"c#|\.net\b", "Go": r"\bgolang\b|\bgo\b(?=,|\s*/|\s+(?:and|or)\b)", "Rust": r"\brust\b", "Scala": r"\bscala\b",
    "R": r"\br\b(?=,|\s*/|\s+(?:and|or)\b|\s+programming)", "JavaScript": r"\bjavascript\b|\bjs\b", "TypeScript": r"\btypescript\b",
    "Bash": r"\bbash\b|\bshell scripting\b", "Kotlin": r"\bkotlin\b", "Swift": r"\bswift\b", "MATLAB": r"\bmatlab\b",
    # ML / AI
    "Machine Learning": r"machine learning|\bml\b", "Deep Learning": r"deep learning|neural networks?", "NLP": r"\bnlp\b|natural language",
    "Computer Vision": r"computer vision|\bcv\b(?= |,)|image (?:recognition|processing)", "Generative AI": r"generative ai|\bgen ?ai\b",
    "LLMs": r"\bllms?\b|large language models?", "RAG": r"\brag\b|retrieval[- ]augmented", "Agents": r"\bai agents?\b|\bagentic\b|multi-agent|llm agents?",
    "Fine-tuning": r"fine[- ]?tun", "LoRA/QLoRA": r"\bq?lora\b|\bpeft\b", "RLHF/DPO": r"\brlhf\b|\bdpo\b|\bgrpo\b|preference optimization|reinforcement learning from human",
    "Reinforcement Learning": r"reinforcement learning", "Evaluation/Evals": r"\bevals?\b|evaluation (?:frameworks?|harness|pipelines?)|model evaluation|llm-as-a?-?judge",
    "Prompt Engineering": r"prompt engineering|prompting", "Transformers": r"\btransformers?\b", "PyTorch": r"\bpytorch\b|\btorch\b",
    "TensorFlow": r"\btensorflow\b|\bkeras\b", "JAX": r"\bjax\b", "scikit-learn": r"scikit[- ]learn|\bsklearn\b", "XGBoost": r"\bxgboost\b|\blightgbm\b|gradient boost",
    "Hugging Face": r"hugging ?face", "vLLM": r"\bvllm\b", "LangChain": r"\blangchain\b", "LangGraph": r"\blanggraph\b", "LlamaIndex": r"\bllama ?index\b",
    "OpenAI/Anthropic APIs": r"\bopenai\b|\banthropic\b|\bclaude\b|\bgpt-?\d", "Vector DBs": r"vector (?:database|db|store|search)|\bpinecone\b|\bweaviate\b|\bqdrant\b|\bfaiss\b|\bmilvus\b|\bchroma\b|pgvector",
    "Embeddings": r"\bembeddings?\b", "MCP": r"model context protocol|\bmcp\b", "MLOps": r"\bmlops\b|ml (?:infrastructure|platform|pipelines?)|model (?:deployment|serving)",
    "MLflow": r"\bmlflow\b", "Weights & Biases": r"weights (?:&|and) biases|\bw&b\b|\bwandb\b", "Statistics": r"\bstatistic|probability|hypothesis test",
    "A/B Testing": r"a/b test|experimentation|causal inference", "Time Series": r"time[- ]series|forecasting", "Recommender Systems": r"recommend(?:er|ation) systems?|ranking systems?",
    "CUDA/GPU": r"\bcuda\b|\bgpus?\b|triton", "Distributed Training": r"distributed training|\bdeepspeed\b|\bfsdp\b|megatron",
    # data
    "pandas": r"\bpandas\b", "NumPy": r"\bnumpy\b", "Spark": r"\bspark\b|pyspark", "Airflow": r"\bairflow\b", "Kafka": r"\bkafka\b", "dbt": r"\bdbt\b",
    "Snowflake": r"\bsnowflake\b", "Databricks": r"\bdatabricks\b", "BigQuery": r"\bbigquery\b", "Redshift": r"\bredshift\b", "Hadoop": r"\bhadoop\b|\bhive\b",
    "ETL/Data Pipelines": r"\betl\b|\belt\b|data pipelines?", "Data Visualization": r"data visuali[sz]ation|\btableau\b|power ?bi|\blooker\b|matplotlib|plotly",
    "Excel": r"\bexcel\b", "Tableau": r"\btableau\b", "Power BI": r"power ?bi",
    # backend / infra
    "FastAPI": r"\bfastapi\b", "Flask": r"\bflask\b", "Django": r"\bdjango\b", "Node.js": r"\bnode(?:\.js|js)?\b", "React": r"\breact\b", "Next.js": r"next\.js|\bnextjs\b",
    "REST APIs": r"\brest(?:ful)?\b|\bapis?\b", "GraphQL": r"\bgraphql\b", "gRPC": r"\bgrpc\b", "Microservices": r"microservices?",
    "Distributed Systems": r"distributed systems?", "System Design": r"system design|scalab", "PostgreSQL": r"\bpostgres(?:ql)?\b",
    "MySQL": r"\bmysql\b", "MongoDB": r"\bmongo(?:db)?\b", "Redis": r"\bredis\b", "Elasticsearch": r"elasticsearch|opensearch",
    "NoSQL": r"\bnosql\b|\bdynamodb\b|\bcassandra\b", "AWS": r"\baws\b|amazon web services|\bsagemaker\b|\bbedrock\b|\blambda\b|\bs3\b|\bec2\b",
    "GCP": r"\bgcp\b|google cloud|vertex ai", "Azure": r"\bazure\b", "Docker": r"\bdocker\b|containeri[sz]", "Kubernetes": r"\bkubernetes\b|\bk8s\b",
    "Terraform": r"\bterraform\b|infrastructure as code", "CI/CD": r"\bci/cd\b|continuous integration|github actions|jenkins", "Git": r"\bgit\b|github|gitlab",
    "Linux": r"\blinux\b|\bunix\b", "Testing": r"unit test|test-driven|\bpytest\b|automated test", "Observability": r"observability|monitoring|datadog|prometheus|grafana",
    "Security": r"\bsecurity\b",
}

SKILLS = {name: re.compile(rx, re.IGNORECASE) for name, rx in _RAW.items()}


def detect(text: str) -> set[str]:
    return {name for name, rx in SKILLS.items() if rx.search(text)}
