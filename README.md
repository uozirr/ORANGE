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

Пример с настройками:

```bash
python orange_bot.py --e-cooldown 2 --post-pick-cooldown 1.5 --move-duration 1.5 --turn-pixels 1400 --turn-duration 0.35 --max-targets 24
```

## Опционально: LLM-подсказки восстановления (через Ollama)

```bash
ollama run llama3.1:8b
python orange_bot.py --enable-llm --llm-model llama3.1:8b
```

Если Ollama работает на нестандартном адресе:

```bash
export OLLAMA_HOST=http://127.0.0.1:11434
```

## Важные замечания по точности

- Если поворот не 180°, подбирайте `--turn-pixels` (обычно 900..2200 в зависимости от sensitivity).
- Если поворот слишком резкий/медленный, подбирайте `--turn-duration`.
- Если видит не все апельсины, увеличьте `--max-targets` и убедитесь, что апельсины реально видны в кадре (не закрыты листьями).
