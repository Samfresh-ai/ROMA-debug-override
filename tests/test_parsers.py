"""Tests for the multi-language parser system."""

import pytest
from roma_debug.core.models import Language, Symbol, Import
from roma_debug.parsers.base import BaseParser
from roma_debug.parsers.registry import detect_language, get_parser, get_registry
from roma_debug.parsers.python_ast_parser import PythonAstParser


class TestLanguageDetection:
    """Tests for language detection from file extensions."""

    def test_python_extensions(self):
        assert detect_language("main.py") == Language.PYTHON
        assert detect_language("script.pyw") == Language.PYTHON
        assert detect_language("types.pyi") == Language.PYTHON

    def test_javascript_extensions(self):
        assert detect_language("app.js") == Language.JAVASCRIPT
        assert detect_language("module.mjs") == Language.JAVASCRIPT
        assert detect_language("common.cjs") == Language.JAVASCRIPT
        assert detect_language("component.jsx") == Language.JAVASCRIPT

    def test_typescript_extensions(self):
        assert detect_language("app.ts") == Language.TYPESCRIPT
        assert detect_language("component.tsx") == Language.TYPESCRIPT
        assert detect_language("module.mts") == Language.TYPESCRIPT

    def test_go_extension(self):
        assert detect_language("main.go") == Language.GO

    def test_rust_extension(self):
        assert detect_language("lib.rs") == Language.RUST

    def test_java_extension(self):
        assert detect_language("Main.java") == Language.JAVA

    def test_unknown_extension(self):
        assert detect_language("file.xyz") == Language.UNKNOWN
        assert detect_language("noextension") == Language.UNKNOWN


class TestPythonAstParser:
    """Tests for the Python AST parser."""

    def test_parse_simple_function(self):
        source = '''
def hello(name):
    """Say hello."""
    return f"Hello, {name}!"
'''
        parser = PythonAstParser()
        assert parser.parse(source, "test.py") is True
        assert parser.is_parsed

    def test_find_enclosing_function(self):
        source = '''
def outer():
    x = 1
    def inner():
        y = 2
        return y
    return inner()
'''
        parser = PythonAstParser()
        parser.parse(source, "test.py")

        # Line 5 is inside inner()
        symbol = parser.find_enclosing_symbol(5)
        assert symbol is not None
        assert symbol.name == "inner"
        assert symbol.kind == "function"

        # Line 3 is inside outer()
        symbol = parser.find_enclosing_symbol(3)
        assert symbol is not None
        assert symbol.name == "outer"

    def test_find_enclosing_class(self):
        source = '''
class MyClass:
    """A test class."""

    def method(self):
        return 42
'''
        parser = PythonAstParser()
        parser.parse(source, "test.py")

        # Line 5 is inside method()
        symbol = parser.find_enclosing_symbol(5)
        assert symbol is not None
        assert symbol.name == "method"
        assert symbol.kind == "method"

        # Class should be on line 2
        symbol = parser.find_enclosing_symbol(2)
        assert symbol is not None
        assert symbol.name == "MyClass"
        assert symbol.kind == "class"

    def test_extract_imports(self):
        source = '''
import os
import sys as system
from pathlib import Path
from typing import Optional, List
from . import local_module
from ..parent import something
'''
        parser = PythonAstParser()
        parser.parse(source, "test.py")

        imports = parser.extract_imports()
        assert len(imports) == 6

        # Check import os
        os_import = next((i for i in imports if i.module_name == "os"), None)
        assert os_import is not None
        assert os_import.alias is None

        # Check import sys as system
        sys_import = next((i for i in imports if i.module_name == "sys"), None)
        assert sys_import is not None
        assert sys_import.alias == "system"

        # Check from pathlib import Path
        pathlib_import = next((i for i in imports if i.module_name == "pathlib"), None)
        assert pathlib_import is not None
        assert "Path" in pathlib_import.imported_names

        # Check relative import
        relative_import = next((i for i in imports if i.is_relative and i.relative_level == 1), None)
        assert relative_import is not None

    def test_async_function(self):
        source = '''
async def fetch_data(url):
    response = await client.get(url)
    return response.json()
'''
        parser = PythonAstParser()
        parser.parse(source, "test.py")

        symbol = parser.find_enclosing_symbol(3)
        assert symbol is not None
        assert symbol.name == "fetch_data"
        assert symbol.kind == "async_function"

    def test_decorators(self):
        source = '''
@staticmethod
@some_decorator
def decorated_function():
    pass
'''
        parser = PythonAstParser()
        parser.parse(source, "test.py")

        symbols = parser.find_all_symbols()
        assert len(symbols) == 1
        assert "staticmethod" in symbols[0].decorators
        assert "some_decorator" in symbols[0].decorators

    def test_syntax_error_returns_false(self):
        source = '''
def broken(
    # missing closing paren and body
'''
        parser = PythonAstParser()
        assert parser.parse(source, "test.py") is False
        assert not parser.is_parsed

    def test_format_snippet(self):
        source = "line1\nline2\nline3\nline4\nline5"
        parser = PythonAstParser()
        parser.parse(source, "test.py")

        snippet = parser.format_snippet(2, 4, highlight_line=3)
        assert ">> " in snippet  # Highlight marker
        assert "line2" in snippet
        assert "line3" in snippet
        assert "line4" in snippet


class TestParserRegistry:
    """Tests for the parser registry."""

    def test_get_python_parser(self):
        parser = get_parser(Language.PYTHON)
        assert parser is not None
        assert parser.language == Language.PYTHON

    def test_get_parser_by_filepath(self):
        parser = get_parser("test.py")
        assert parser is not None
        assert parser.language == Language.PYTHON

    def test_registry_caches_parsers(self):
        parser1 = get_parser(Language.PYTHON, create_new=False)
        parser2 = get_parser(Language.PYTHON, create_new=False)
        assert parser1 is parser2

    def test_create_new_parser(self):
        parser1 = get_parser(Language.PYTHON, create_new=True)
        parser2 = get_parser(Language.PYTHON, create_new=True)
        assert parser1 is not parser2

    def test_registry_supports_language(self):
        registry = get_registry()
        assert registry.supports_language(Language.PYTHON)

    def test_unsupported_language_returns_none(self):
        parser = get_parser(Language.UNKNOWN)
        assert parser is None


class TestSymbol:
    """Tests for the Symbol class."""

    def test_contains_line(self):
        symbol = Symbol(
            name="test",
            kind="function",
            start_line=10,
            end_line=20,
        )
        assert symbol.contains_line(10)
        assert symbol.contains_line(15)
        assert symbol.contains_line(20)
        assert not symbol.contains_line(9)
        assert not symbol.contains_line(21)

    def test_qualified_name_no_parent(self):
        symbol = Symbol(name="func", kind="function", start_line=1, end_line=5)
        assert symbol.qualified_name == "func"

    def test_qualified_name_with_parent(self):
        parent = Symbol(name="MyClass", kind="class", start_line=1, end_line=20)
        child = Symbol(name="method", kind="method", start_line=5, end_line=10, parent=parent)
        assert child.qualified_name == "MyClass.method"


class TestImport:
    """Tests for the Import class."""

    def test_python_import_string(self):
        imp = Import(
            module_name="os",
            language=Language.PYTHON,
        )
        assert imp.full_import_string == "import os"

    def test_python_import_with_alias(self):
        imp = Import(
            module_name="numpy",
            alias="np",
            language=Language.PYTHON,
        )
        assert imp.full_import_string == "import numpy as np"

    def test_python_from_import(self):
        imp = Import(
            module_name="pathlib",
            imported_names=["Path", "PurePath"],
            language=Language.PYTHON,
        )
        assert "from pathlib import" in imp.full_import_string
        assert "Path" in imp.full_import_string

    def test_python_relative_import(self):
        imp = Import(
            module_name="utils",
            imported_names=["helper"],
            is_relative=True,
            relative_level=2,
            language=Language.PYTHON,
        )
        assert "from ..utils import" in imp.full_import_string

    def test_javascript_import_string(self):
        imp = Import(
            module_name="./utils",
            alias="utils",
            language=Language.JAVASCRIPT,
        )
        assert "import utils from" in imp.full_import_string

    def test_javascript_named_import(self):
        imp = Import(
            module_name="lodash",
            imported_names=["map", "filter"],
            language=Language.JAVASCRIPT,
        )
        assert "import {" in imp.full_import_string
        assert "map" in imp.full_import_string


class TestTreeSitterParser:
    """Tests for the TreeSitter multi-language parser."""

    def test_tree_sitter_available(self):
        """Verify tree-sitter is installed and available."""
        from roma_debug.parsers.treesitter_parser import TREE_SITTER_AVAILABLE
        assert TREE_SITTER_AVAILABLE, "tree-sitter should be available"

    def test_javascript_parse_function(self):
        """Test parsing JavaScript function."""
        source = '''
function greet(name) {
    console.log("Hello, " + name);
    return true;
}

function multiply(x, y) {
    return x * y;
}
'''
        parser = get_parser(Language.JAVASCRIPT, create_new=True)
        assert parser is not None
        assert parser.parse(source, "test.js") is True

        # Find symbols
        symbols = parser.find_all_symbols()
        names = [s.name for s in symbols]
        assert "greet" in names
        assert "multiply" in names

    def test_javascript_find_enclosing_symbol(self):
        """Test finding enclosing function in JavaScript."""
        source = '''function outer() {
    let x = 1;
    function inner() {
        let y = 2;
        return y;
    }
    return inner();
}'''
        parser = get_parser(Language.JAVASCRIPT, create_new=True)
        parser.parse(source, "test.js")

        # Line 4 is inside inner()
        symbol = parser.find_enclosing_symbol(4)
        assert symbol is not None
        assert symbol.name == "inner"

    def test_javascript_extract_imports(self):
        """Test extracting JavaScript imports."""
        source = '''
import React from 'react';
import { useState, useEffect } from 'react';
import * as utils from './utils';
const fs = require('fs');
'''
        parser = get_parser(Language.JAVASCRIPT, create_new=True)
        parser.parse(source, "test.js")

        imports = parser.extract_imports()
        module_names = [i.module_name for i in imports]
        assert "react" in module_names or "'react'" in module_names

    def test_go_parse_function(self):
        """Test parsing Go function."""
        source = '''
package main

import "fmt"

func greet(name string) string {
    return fmt.Sprintf("Hello, %s!", name)
}

func main() {
    msg := greet("World")
    fmt.Println(msg)
}
'''
        parser = get_parser(Language.GO, create_new=True)
        assert parser is not None
        assert parser.parse(source, "main.go") is True

        symbols = parser.find_all_symbols()
        names = [s.name for s in symbols]
        assert "greet" in names
        assert "main" in names

    def test_go_find_enclosing_symbol(self):
        """Test finding enclosing function in Go."""
        source = '''package main

func process(data []int) int {
    sum := 0
    for _, v := range data {
        sum += v
    }
    return sum
}'''
        parser = get_parser(Language.GO, create_new=True)
        parser.parse(source, "main.go")

        # Line 5 is inside for loop in process()
        symbol = parser.find_enclosing_symbol(5)
        assert symbol is not None
        assert symbol.name == "process"

    def test_go_extract_imports(self):
        """Test extracting Go imports."""
        source = '''
package main

import (
    "fmt"
    "os"
    "strings"
)

func main() {}
'''
        parser = get_parser(Language.GO, create_new=True)
        parser.parse(source, "main.go")

        imports = parser.extract_imports()
        module_names = [i.module_name for i in imports]
        assert any("fmt" in m for m in module_names)

    def test_rust_parse_function(self):
        """Test parsing Rust function."""
        source = '''
fn greet(name: &str) -> String {
    format!("Hello, {}!", name)
}

pub fn main() {
    let msg = greet("World");
    println!("{}", msg);
}

struct Point {
    x: i32,
    y: i32,
}

impl Point {
    fn new(x: i32, y: i32) -> Self {
        Point { x, y }
    }
}
'''
        parser = get_parser(Language.RUST, create_new=True)
        assert parser is not None
        assert parser.parse(source, "main.rs") is True

        symbols = parser.find_all_symbols()
        names = [s.name for s in symbols]
        assert "greet" in names
        assert "main" in names
        assert "Point" in names

    def test_rust_find_enclosing_symbol(self):
        """Test finding enclosing function in Rust."""
        source = '''fn process(data: Vec<i32>) -> i32 {
    let mut sum = 0;
    for v in data {
        sum += v;
    }
    sum
}'''
        parser = get_parser(Language.RUST, create_new=True)
        parser.parse(source, "main.rs")

        # Line 3 is inside for loop
        symbol = parser.find_enclosing_symbol(3)
        assert symbol is not None
        assert symbol.name == "process"

    def test_java_parse_class(self):
        """Test parsing Java class and methods."""
        source = '''
public class Calculator {
    private int value;

    public Calculator() {
        this.value = 0;
    }

    public int add(int x) {
        this.value += x;
        return this.value;
    }

    public static void main(String[] args) {
        Calculator calc = new Calculator();
        System.out.println(calc.add(5));
    }
}
'''
        parser = get_parser(Language.JAVA, create_new=True)
        assert parser is not None
        assert parser.parse(source, "Calculator.java") is True

        symbols = parser.find_all_symbols()
        names = [s.name for s in symbols]
        assert "Calculator" in names
        assert "add" in names
        assert "main" in names

    def test_format_snippet_with_highlight(self):
        """Test snippet formatting with highlight line."""
        source = "line1\nline2\nline3\nline4\nline5"
        parser = get_parser(Language.JAVASCRIPT, create_new=True)
        parser.parse(source, "test.js")

        snippet = parser.format_snippet(2, 4, highlight_line=3)
        assert "line2" in snippet
        assert "line3" in snippet
        assert "line4" in snippet
        # Should have highlight marker on line 3
        lines = snippet.split("\n")
        line3 = [l for l in lines if "line3" in l][0]
        assert ">>" in line3

    def test_parser_fallback_gracefully(self):
        """Test that parsers handle invalid input gracefully."""
        parser = get_parser(Language.JAVASCRIPT, create_new=True)

        # Parse valid code first
        valid = "function test() { return 1; }"
        assert parser.parse(valid, "test.js") is True

        # Now parse invalid/partial code - should still attempt parse
        partial = "function incomplete("
        result = parser.parse(partial, "broken.js")
        # Tree-sitter is lenient, may still produce partial AST
        # The important thing is it doesn't crash
