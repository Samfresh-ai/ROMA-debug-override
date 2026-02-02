"""Tests for multi-language traceback pattern matching."""

import pytest
from roma_debug.core.models import Language
from roma_debug.parsers.traceback_patterns import (
    detect_traceback_language,
    parse_traceback,
    extract_frames,
    extract_file_line_pairs,
)


class TestLanguageDetection:
    """Tests for traceback language detection."""

    def test_detect_python_traceback(self):
        traceback = '''
Traceback (most recent call last):
  File "/app/main.py", line 10, in main
    result = process()
  File "/app/utils.py", line 25, in process
    return compute(data)
ValueError: invalid literal for int()
'''
        assert detect_traceback_language(traceback) == Language.PYTHON

    def test_detect_javascript_stacktrace(self):
        traceback = '''
Error: Cannot read property 'x' of undefined
    at processData (/app/src/utils.js:15:23)
    at main (/app/src/index.js:42:10)
    at Object.<anonymous> (/app/src/index.js:50:1)
'''
        assert detect_traceback_language(traceback) == Language.JAVASCRIPT

    def test_detect_go_panic(self):
        traceback = '''
panic: runtime error: invalid memory address or nil pointer dereference
[signal SIGSEGV: segmentation violation code=0x1 addr=0x0 pc=0x49c2ef]

goroutine 1 [running]:
main.processData(0x0, 0x0)
	/app/main.go:25 +0x1f
main.main()
	/app/main.go:15 +0x3a
'''
        assert detect_traceback_language(traceback) == Language.GO

    def test_detect_rust_panic(self):
        traceback = '''
thread 'main' panicked at 'called `Option::unwrap()` on a `None` value', src/main.rs:15:10
stack backtrace:
   0: std::panicking::begin_panic
   1: core::option::Option<T>::unwrap
             at /rustc/xxx/library/core/src/option.rs:777:21
   2: myapp::process_data
             at ./src/main.rs:15:10
'''
        assert detect_traceback_language(traceback) == Language.RUST

    def test_detect_java_exception(self):
        traceback = '''
Exception in thread "main" java.lang.NullPointerException
	at com.example.MyClass.processData(MyClass.java:25)
	at com.example.Main.main(Main.java:15)
Caused by: java.lang.IllegalArgumentException: Invalid input
	at com.example.Utils.validate(Utils.java:42)
'''
        assert detect_traceback_language(traceback) == Language.JAVA


class TestPythonTraceback:
    """Tests for Python traceback parsing."""

    def test_simple_traceback(self):
        traceback = '''
Traceback (most recent call last):
  File "/app/main.py", line 10, in main
    result = process()
ValueError: invalid value
'''
        result = parse_traceback(traceback)

        assert result.language == Language.PYTHON
        assert len(result.frames) >= 1
        assert result.frames[0].filepath == "/app/main.py"
        assert result.frames[0].line_number == 10
        assert result.frames[0].function_name == "main"

    def test_multi_file_traceback(self):
        traceback = '''
Traceback (most recent call last):
  File "/app/main.py", line 10, in main
    result = process()
  File "/app/utils.py", line 25, in process
    return compute(data)
  File "/app/compute.py", line 5, in compute
    return int(value)
ValueError: invalid literal
'''
        result = parse_traceback(traceback)

        assert len(result.frames) == 3
        assert result.frames[0].filepath == "/app/main.py"
        assert result.frames[1].filepath == "/app/utils.py"
        assert result.frames[2].filepath == "/app/compute.py"

    def test_error_extraction(self):
        traceback = '''
Traceback (most recent call last):
  File "/app/main.py", line 10, in main
    result = int("abc")
ValueError: invalid literal for int() with base 10: 'abc'
'''
        result = parse_traceback(traceback)

        assert result.error_type == "ValueError"
        assert "invalid literal" in result.error_message


class TestJavaScriptStackTrace:
    """Tests for JavaScript/Node.js stack trace parsing."""

    def test_node_stacktrace(self):
        traceback = '''
TypeError: Cannot read property 'name' of undefined
    at processUser (/app/src/users.js:25:15)
    at main (/app/src/index.js:10:5)
'''
        result = parse_traceback(traceback, Language.JAVASCRIPT)

        assert result.language == Language.JAVASCRIPT
        assert len(result.frames) >= 1
        assert "/app/src/users.js" in result.frames[0].filepath
        assert result.frames[0].line_number == 25

    def test_anonymous_function(self):
        traceback = '''
Error: Something went wrong
    at /app/src/index.js:42:10
    at Object.<anonymous> (/app/src/index.js:50:1)
'''
        result = parse_traceback(traceback, Language.JAVASCRIPT)

        assert len(result.frames) >= 1


class TestGoTraceback:
    """Tests for Go panic/stacktrace parsing."""

    def test_go_panic(self):
        traceback = '''
panic: runtime error: index out of range

goroutine 1 [running]:
main.processData()
	/app/main.go:25 +0x1f
main.main()
	/app/main.go:15 +0x3a
'''
        result = parse_traceback(traceback, Language.GO)

        assert result.language == Language.GO
        assert len(result.frames) >= 1
        # Should find main.go references
        assert any("main.go" in f.filepath for f in result.frames)


class TestRustTraceback:
    """Tests for Rust panic parsing."""

    def test_rust_panic(self):
        traceback = '''
thread 'main' panicked at 'index out of bounds', src/main.rs:15:10
'''
        result = parse_traceback(traceback, Language.RUST)

        assert result.language == Language.RUST
        assert len(result.frames) >= 1
        assert "main.rs" in result.frames[0].filepath
        assert result.frames[0].line_number == 15


class TestJavaTraceback:
    """Tests for Java exception parsing."""

    def test_java_exception(self):
        traceback = '''
java.lang.NullPointerException
	at com.example.MyClass.process(MyClass.java:25)
	at com.example.Main.main(Main.java:10)
'''
        result = parse_traceback(traceback, Language.JAVA)

        assert result.language == Language.JAVA
        assert len(result.frames) >= 1
        assert "MyClass.java" in result.frames[0].filepath
        assert result.frames[0].line_number == 25


class TestExtractFilePairs:
    """Tests for simple file/line extraction."""

    def test_extract_python_pairs(self):
        traceback = '''
File "/app/main.py", line 10
File "/app/utils.py", line 25
'''
        pairs = extract_file_line_pairs(traceback)

        assert len(pairs) == 2
        assert ("/app/main.py", 10) in pairs
        assert ("/app/utils.py", 25) in pairs

    def test_extract_with_language_hint(self):
        traceback = '''
	at com.example.Main.main(Main.java:10)
'''
        pairs = extract_file_line_pairs(traceback, Language.JAVA)

        assert len(pairs) >= 1
        assert any(p[0].endswith("Main.java") for p in pairs)
