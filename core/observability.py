import json
import time
import uuid
from typing import Dict, Any, Optional
from datetime import datetime
import os

class Telemetry:
    def __init__(self, log_dir: str = "logs"):
        self.log_dir = log_dir
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
        self.current_trace_id = None
        self.spans = []

    def start_trace(self) -> str:
        self.current_trace_id = str(uuid.uuid4())
        self.spans = []
        return self.current_trace_id

    def log_span(self, name: str, input_data: Any = None, output_data: Any = None, duration_ms: float = 0.0):
        span = {
            "trace_id": self.current_trace_id,
            "span_id": str(uuid.uuid4()),
            "name": name,
            "timestamp": datetime.now().isoformat(),
            "duration_ms": duration_ms,
            "input": str(input_data)[:500] if input_data else None, # Truncate for sanity
            "output": str(output_data)[:500] if output_data else None
        }
        self.spans.append(span)

    def flush(self):
        if not self.current_trace_id:
            return
            
        filename = os.path.join(self.log_dir, f"trace_{self.current_trace_id}.jsonl")
        with open(filename, "w") as f:
            for span in self.spans:
                f.write(json.dumps(span) + "\n")
        
        # Reset
        self.current_trace_id = None
        self.spans = []

# Global singleton
telemetry = Telemetry()

def trace(name: str):
    def decorator(func):
        def wrapper(*args, **kwargs):
            start = time.time()
            try:
                result = func(*args, **kwargs)
                duration = (time.time() - start) * 1000
                telemetry.log_span(name, input_data=kwargs, output_data=result, duration_ms=duration)
                return result
            except Exception as e:
                duration = (time.time() - start) * 1000
                telemetry.log_span(name, input_data=kwargs, output_data={"error": str(e)}, duration_ms=duration)
                raise e
        return wrapper
    return decorator
