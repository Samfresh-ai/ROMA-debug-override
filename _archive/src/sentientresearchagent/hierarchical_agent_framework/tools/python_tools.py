class PythonTools:
    def __init__(self):
        print("[PythonTools] initialized")

    def run(self, code: str):
        print(f"[PythonTools] received code:\n{code}")
        return {"output": "stubbed"}

