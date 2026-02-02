; Tree-sitter query patterns for JavaScript
; Used to extract semantic information from JavaScript source code

; Function declarations
(function_declaration
  name: (identifier) @function.name
  parameters: (formal_parameters) @function.params
  body: (statement_block) @function.body) @function

; Function expressions
(variable_declarator
  name: (identifier) @function.name
  value: (function_expression
    parameters: (formal_parameters) @function.params
    body: (statement_block) @function.body)) @function

; Arrow functions
(variable_declarator
  name: (identifier) @arrow_function.name
  value: (arrow_function
    parameters: (_) @arrow_function.params
    body: (_) @arrow_function.body)) @arrow_function

; Async functions
(function_declaration
  "async" @async
  name: (identifier) @async_function.name) @async_function

; Class declarations
(class_declaration
  name: (identifier) @class.name
  body: (class_body) @class.body) @class

; Class expressions
(variable_declarator
  name: (identifier) @class.name
  value: (class
    body: (class_body) @class.body)) @class

; Class with extends
(class_declaration
  name: (identifier) @class.name
  (class_heritage
    (identifier) @class.extends)
  body: (class_body) @class.body) @class

; Method definitions
(method_definition
  name: (property_identifier) @method.name
  parameters: (formal_parameters) @method.params
  body: (statement_block) @method.body) @method

; Static methods
(method_definition
  "static" @static
  name: (property_identifier) @static_method.name) @static_method

; Getter/Setter
(method_definition
  "get" @getter
  name: (property_identifier) @getter.name) @getter

(method_definition
  "set" @setter
  name: (property_identifier) @setter.name) @setter

; Import statements (ES6)
(import_statement
  (import_clause
    (identifier) @import.default)
  source: (string) @import.source) @import

(import_statement
  (import_clause
    (named_imports
      (import_specifier
        name: (identifier) @import.name)))
  source: (string) @import.source) @import

(import_statement
  (import_clause
    (namespace_import
      (identifier) @import.namespace))
  source: (string) @import.source) @import

; Require (CommonJS)
(variable_declarator
  name: (identifier) @require.name
  value: (call_expression
    function: (identifier) @_require (#eq? @_require "require")
    arguments: (arguments (string) @require.module))) @require

; Export statements
(export_statement
  declaration: (function_declaration
    name: (identifier) @export.function)) @export

(export_statement
  declaration: (class_declaration
    name: (identifier) @export.class)) @export

(export_statement
  declaration: (variable_declaration
    (variable_declarator
      name: (identifier) @export.variable))) @export

; Default export
(export_statement
  "default" @default
  declaration: (_) @export.default) @export
