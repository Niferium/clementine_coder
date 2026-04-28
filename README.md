# Clementine Coder
A coding ancilla that helps building prototypes, code reviews, analyst

## Overview
Clementine Coder is an AI coding assistant that can be locally deployed designed to help developers write code faster and more efficiently. It comes in three flavors:

### 🎯 Clementine CLI
The command-line interface version of Clementine that you can interact with

#### Project Structure
```
clem_cli/
├──output (# location of created outputs)
├── src/
│ ├── log
│     └── logger.py
│ ├── prompts
│     └── sys_prompt.py
│ └── config.py
└── main.py
```

### 💬 Clementine Chat
The web-based chat interface that provides a clean conversational UI coding experience.

#### Project Structure
```
clem_chat/
├──output (# location of created outputs)
├── src/
│ ├── log
│     └── logger.py
│ ├── prompts
│     └── sys_prompt.py
│ ├── ui
│     └── index.html
│ ├── config.py
│ └── model_agent.py
└── app.py
```

### 🧪 Clementine Experimental
The experimental version that provides the following
- semantic searching for multi-agent role
- basic multi-agent (from low model then pass to coder if it detects it needs coder)

#### Project Structure
```
clem_experimental/
├──output (# location of created outputs)
├── src/
│ ├── agent.py
│ ├── logger.py
│ ├── router.py
│ ├── self_checker.py
│ ├── server.py
│ ├── skill_parser.py
│ └── token_monitor.py
├── templates/
│ └── index.html
├── run.py
└── skill.md
```


### Requirements
* Mac machines with big memory

#### Create and use virtual env:
    python -m venv <name_env>
    source <name_env>/bin/activate

#### Install dependencies
    pip install -r requirements.txt

### Test Structure

Tests are organized in `test` directory with files like:
- `test_run.py`
- `test_main.py`
- `test_app.py`

open your cli in any of the folder then just run ``pytest``

## License

MIT