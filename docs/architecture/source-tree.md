# **10\. Source Tree**

The project directory will be structured to clearly reflect the Hexagonal Architecture.

Plaintext

market-data-service/  
├── .github/  
│   └── workflows/  
│       └── ci.yml  
├── docs/  
├── src/  
│   ├── adapters/  
│   │   ├── ctp\_adapter.py  
│   │   ├── nats\_publisher.py  
│   │   └── serializers.py  
│   ├── domain/  
│   │   ├── models.py  
│   │   └── ports.py  
│   ├── application/  
│   │   └── services.py  
│   ├── config.py  
│   └── \_\_main\_\_.py  
├── tests/  
│   ├── integration/  
│   └── unit/  
├── .dockerignore  
├── docker-compose.yml  
├── Dockerfile  
├── pyproject.toml  
└── README.md

---
