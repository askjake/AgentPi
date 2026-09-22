# Intelligent Agent System

## Overview
This is a **self-improving AI agent** with full intelligence capabilities:

### Features
✅ **Conversation Memory** - Persists all conversations with full context
✅ **Self-Reflection** - Journals and learns from every interaction
✅ **Methodology Evolution** - Updates its own instructions based on effectiveness
✅ **Personality Adaptation** - Adjusts behavior based on user interactions
✅ **Tool Integration** - Full access to 9+ agent tools
✅ **Semantic Search** - RAG-based context retrieval (future: embeddings)

## Architecture

### Database Schema
- **conversations** & **messages** - Full chat history
- **journal_entries** & **insights** - Self-reflection and learnings
- **methodology_rules** & **snapshots** - Dynamic best practices
- **personality_profiles** - Adaptive behavior patterns

### Services
- **MemoryService** - Conversation retrieval and context
- **JournalService** - Self-reflection and insight extraction
- **MethodologyService** - Dynamic rule evolution
- **PersonalityService** - Behavior adaptation

## Installation

### 1. Setup PostgreSQL
```bash
sudo apt-get install postgresql postgresql-contrib
sudo -u postgres createuser dishchat -P  # Password: dishchat
sudo -u postgres createdb dishchat -O dishchat
```

### 2. Create Virtual Environment
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure Environment
```bash
cp .env.template .env
# Edit .env with your configuration
```

### 4. Initialize Database
```bash
python3 init_database.py
```

### 5. Start Backend
```bash
./start_intelligent.sh
```

## API Endpoints

### Chat
- `POST /api/chat` - Intelligent chat with memory

### Memory
- `GET /api/conversations` - List conversations
- `GET /api/conversations/<chat_id>` - Get conversation history

### Intelligence
- `GET /api/journal` - View journal entries
- `GET /api/insights` - Get extracted insights
- `GET /api/methodology` - View active methodology rules
- `GET /api/statistics` - System statistics

### Health
- `GET /health` - System health and features

## How It Works

### 1. Message Flow
```
User Message → Memory (Store) → Context Retrieval → 
LLM with Enhanced Context → Response → Memory (Store) → 
Background Reflection (every 5 msgs)
```

### 2. Self-Improvement Loop
```
Conversation → Reflection → Insights → 
Methodology Updates → Better Future Responses
```

### 3. Personality Adaptation
```
User Interactions → Trait Adjustments → 
Communication Style Evolution
```

## Monitoring

### View Journal
```bash
curl http://localhost:8000/api/journal?limit=10
```

### View Methodology
```bash
curl http://localhost:8000/api/methodology
```

### View Statistics
```bash
curl http://localhost:8000/api/statistics
```

## Maintenance

### Backup Database
```bash
pg_dump dishchat > backup_$(date +%Y%m%d).sql
```

### View Logs
```bash
tail -f logs/intelligent_backend.log
```

## Troubleshooting

### Database Connection Issues
- Check PostgreSQL is running: `sudo systemctl status postgresql`
- Verify credentials in `.env`
- Test connection: `psql -U dishchat -d dishchat -h localhost`

### Memory Issues
- Monitor with: `curl http://localhost:8000/api/statistics`
- Database may need tuning for Raspberry Pi

## Future Enhancements
- [ ] Vector embeddings for semantic search
- [ ] Background job queue for journaling
- [ ] Web dashboard for intelligence monitoring
- [ ] Export journal as markdown
- [ ] Methodology A/B testing
