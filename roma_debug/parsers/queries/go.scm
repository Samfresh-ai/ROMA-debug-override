; Tree-sitter query patterns for Go
; Used to extract semantic information from Go source code

; Function declarations
(function_declaration
  name: (identifier) @function.name
  parameters: (parameter_list) @function.params
  result: (_)? @function.result
  body: (block) @function.body) @function

; Method declarations (receiver functions)
(method_declaration
  receiver: (parameter_list
    (parameter_declaration
      type: (_) @method.receiver_type)) @method.receiver
  name: (field_identifier) @method.name
  parameters: (parameter_list) @method.params
  result: (_)? @method.result
  body: (block) @method.body) @method

; Type declarations (struct, interface, alias)
(type_declaration
  (type_spec
    name: (type_identifier) @type.name
    type: (struct_type) @type.struct)) @type

(type_declaration
  (type_spec
    name: (type_identifier) @interface.name
    type: (interface_type) @interface.body)) @interface

(type_declaration
  (type_spec
    name: (type_identifier) @type_alias.name
    type: (_) @type_alias.underlying)) @type_alias

; Struct field declarations
(field_declaration
  name: (field_identifier) @field.name
  type: (_) @field.type) @field

; Interface method signatures
(method_spec
  name: (field_identifier) @method_spec.name
  parameters: (parameter_list) @method_spec.params
  result: (_)? @method_spec.result) @method_spec

; Import declarations
(import_declaration
  (import_spec
    path: (interpreted_string_literal) @import.path)) @import

(import_declaration
  (import_spec
    name: (package_identifier) @import.alias
    path: (interpreted_string_literal) @import.path)) @import

(import_declaration
  (import_spec
    name: (blank_identifier) @import.blank
    path: (interpreted_string_literal) @import.path)) @import

(import_declaration
  (import_spec
    name: (dot) @import.dot
    path: (interpreted_string_literal) @import.path)) @import

; Import block
(import_declaration
  (import_spec_list
    (import_spec
      path: (interpreted_string_literal) @import.path))) @import_block

; Package declaration
(package_clause
  (package_identifier) @package.name) @package

; Const declarations
(const_declaration
  (const_spec
    name: (identifier) @const.name
    value: (_)? @const.value)) @const

; Var declarations
(var_declaration
  (var_spec
    name: (identifier) @var.name
    type: (_)? @var.type
    value: (_)? @var.value)) @var

; Short variable declaration
(short_var_declaration
  left: (expression_list
    (identifier) @short_var.name)
  right: (_) @short_var.value) @short_var

; Function call
(call_expression
  function: (identifier) @call.function
  arguments: (argument_list) @call.args) @call

; Method call
(call_expression
  function: (selector_expression
    operand: (_) @call.receiver
    field: (field_identifier) @call.method)
  arguments: (argument_list) @call.args) @method_call

; Defer statement
(defer_statement
  (call_expression
    function: (_) @defer.function)) @defer

; Go statement (goroutine)
(go_statement
  (call_expression
    function: (_) @go.function)) @go

; Error handling pattern
(if_statement
  condition: (binary_expression
    left: (identifier) @error.var
    right: (nil) @error.nil)
  consequence: (block) @error.handler) @error_check
