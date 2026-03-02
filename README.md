# Orange auto-farming helper

Скрипт для автоматизации повторяющегося цикла:
- `Insert` — включить/выключить скрипт.
- `End` — полностью остановить и выйти.
- При включении: нажимает `E`, ждет `2` секунды, находит апельсины на экране и кликает по ним.
- Затем ждет `1.5` секунды, поворачивается, идет вперед `1.5` секунды, разворачивается обратно и снова идет вперед.
- Цикл повторяется.

## Установка

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Запуск

```bash
python orange_bot.py
```

Параметры:

```bash
python orange_bot.py --e-cooldown 2 --post-pick-cooldown 1.5 --move-duration 1.5 --turn-pixels 1200
```

## Опционально: LLM-подсказки восстановления (через Ollama)

Если установлен и запущен Ollama, скрипт может после каждого цикла делать один recovery-шаг (небольшая корректировка действий):

```bash
ollama run llama3.1:8b
python orange_bot.py --enable-llm --llm-model llama3.1:8b
```

Если Ollama работает на нестандартном адресе, можно задать `OLLAMA_HOST`, например:

```bash
export OLLAMA_HOST=http://127.0.0.1:11434
```

> Важно: `turn-pixels` зависит от чувствительности мыши в игре. Подберите вручную, чтобы это было близко к 180°.
