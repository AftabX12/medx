from datetime import datetime
from pathlib import Path

from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.globals["now"] = datetime.now
