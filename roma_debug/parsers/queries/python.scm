; Tree-sitter query patterns for Python
; Used to extract semantic information from Python source code

; Function definitions
(function_definition
  name: (identifier) @function.name
  parameters: (parameters) @function.params
  body: (block) @function.body) @function

; Async function definitions
(async_function_definition
  name: (identifier) @async_function.name
  parameters: (parameters) @async_function.params
  body: (block) @async_function.body) @async_function

; Class definitions
(class_definition
  name: (identifier) @class.name
  body: (block) @class.body) @class

; Class with inheritance
(class_definition
  name: (identifier) @class.name
  superclasses: (argument_list) @class.bases
  body: (block) @class.body) @class

; Method definitions (function inside class)
(class_definition
  body: (block
    (function_definition
      name: (identifier) @method.name
      parameters: (parameters) @method.params) @method))

; Import statements
(import_statement
  name: (dotted_name) @import.module) @import

(import_statement
  name: (aliased_import
    name: (dotted_name) @import.module
    alias: (identifier) @import.alias)) @import

; From imports
(import_from_statement
  module_name: (dotted_name) @import_from.module
  name: (dotted_name) @import_from.name) @import_from

(import_from_statement
  module_name: (relative_import) @import_from.relative
  name: (dotted_name) @import_from.name) @import_from

; Decorators
(decorator
  (identifier) @decorator.name) @decorator

(decorator
  (call
    function: (identifier) @decorator.name)) @decorator

; Variables and assignments
(assignment
  left: (identifier) @variable.name
  right: (_) @variable.value) @variable

; Global variables
(module
  (expression_statement
    (assignment
      left: (identifier) @global.name))) @global
