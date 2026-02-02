; Tree-sitter query patterns for TypeScript
; Extends JavaScript patterns with TypeScript-specific constructs

; Function declarations with types
(function_declaration
  name: (identifier) @function.name
  parameters: (formal_parameters) @function.params
  return_type: (type_annotation)? @function.return_type
  body: (statement_block) @function.body) @function

; Arrow functions with types
(variable_declarator
  name: (identifier) @arrow_function.name
  type: (type_annotation)? @arrow_function.type
  value: (arrow_function
    parameters: (_) @arrow_function.params
    return_type: (type_annotation)? @arrow_function.return_type
    body: (_) @arrow_function.body)) @arrow_function

; Class declarations
(class_declaration
  name: (type_identifier) @class.name
  body: (class_body) @class.body) @class

; Class with implements
(class_declaration
  name: (type_identifier) @class.name
  (implements_clause
    (type_identifier) @class.implements)
  body: (class_body) @class.body) @class

; Interface declarations
(interface_declaration
  name: (type_identifier) @interface.name
  body: (interface_body) @interface.body) @interface

; Interface with extends
(interface_declaration
  name: (type_identifier) @interface.name
  (extends_type_clause
    (type_identifier) @interface.extends)
  body: (interface_body) @interface.body) @interface

; Type alias
(type_alias_declaration
  name: (type_identifier) @type_alias.name
  value: (_) @type_alias.value) @type_alias

; Enum declaration
(enum_declaration
  name: (identifier) @enum.name
  body: (enum_body) @enum.body) @enum

; Method signatures in interface
(method_signature
  name: (property_identifier) @method_signature.name
  parameters: (formal_parameters) @method_signature.params
  return_type: (type_annotation)? @method_signature.return_type) @method_signature

; Property signature in interface
(property_signature
  name: (property_identifier) @property_signature.name
  type: (type_annotation)? @property_signature.type) @property_signature

; Method definitions with types
(method_definition
  name: (property_identifier) @method.name
  parameters: (formal_parameters) @method.params
  return_type: (type_annotation)? @method.return_type
  body: (statement_block) @method.body) @method

; Public/Private/Protected members
(method_definition
  (accessibility_modifier) @modifier
  name: (property_identifier) @method.name) @method

; Import statements (same as JS but with type imports)
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

; Type-only imports
(import_statement
  "type" @type_import
  (import_clause
    (named_imports
      (import_specifier
        name: (identifier) @import.type_name)))
  source: (string) @import.source) @import

; Namespace/Module declaration
(module
  name: (identifier) @namespace.name
  body: (statement_block) @namespace.body) @namespace

; Ambient declarations
(ambient_declaration
  (function_signature
    name: (identifier) @ambient_function.name)) @ambient_function

(ambient_declaration
  (class_declaration
    name: (type_identifier) @ambient_class.name)) @ambient_class

; Decorators (for TypeScript with experimental decorators)
(decorator
  (call_expression
    function: (identifier) @decorator.name)) @decorator

(decorator
  (identifier) @decorator.name) @decorator
