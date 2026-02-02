; Tree-sitter query patterns for Java
; Used to extract semantic information from Java source code

; Class declarations
(class_declaration
  name: (identifier) @class.name
  body: (class_body) @class.body) @class

; Class with modifiers
(class_declaration
  (modifiers) @class.modifiers
  name: (identifier) @class.name
  body: (class_body) @class.body) @class

; Class with extends
(class_declaration
  name: (identifier) @class.name
  superclass: (superclass
    (type_identifier) @class.extends)
  body: (class_body) @class.body) @class

; Class with implements
(class_declaration
  name: (identifier) @class.name
  interfaces: (super_interfaces
    (type_list
      (type_identifier) @class.implements))
  body: (class_body) @class.body) @class

; Interface declarations
(interface_declaration
  name: (identifier) @interface.name
  body: (interface_body) @interface.body) @interface

; Interface with extends
(interface_declaration
  name: (identifier) @interface.name
  (extends_interfaces
    (type_list
      (type_identifier) @interface.extends))
  body: (interface_body) @interface.body) @interface

; Enum declarations
(enum_declaration
  name: (identifier) @enum.name
  body: (enum_body) @enum.body) @enum

; Enum constant
(enum_constant
  name: (identifier) @enum_constant.name) @enum_constant

; Method declarations
(method_declaration
  name: (identifier) @method.name
  parameters: (formal_parameters) @method.params
  body: (block)? @method.body) @method

; Method with return type
(method_declaration
  type: (_) @method.return_type
  name: (identifier) @method.name
  parameters: (formal_parameters) @method.params
  body: (block)? @method.body) @method

; Method with modifiers
(method_declaration
  (modifiers) @method.modifiers
  name: (identifier) @method.name) @method

; Constructor declarations
(constructor_declaration
  name: (identifier) @constructor.name
  parameters: (formal_parameters) @constructor.params
  body: (constructor_body) @constructor.body) @constructor

; Field declarations
(field_declaration
  type: (_) @field.type
  declarator: (variable_declarator
    name: (identifier) @field.name)) @field

; Static field
(field_declaration
  (modifiers
    "static" @static)
  declarator: (variable_declarator
    name: (identifier) @static_field.name)) @static_field

; Constant (static final)
(field_declaration
  (modifiers
    "static" @_static
    "final" @_final)
  declarator: (variable_declarator
    name: (identifier) @constant.name)) @constant

; Import declarations
(import_declaration
  (scoped_identifier) @import.path) @import

; Static import
(import_declaration
  "static" @static_import
  (scoped_identifier) @import.static_path) @import

; Wildcard import
(import_declaration
  (scoped_identifier
    (asterisk) @import.wildcard)) @import

; Package declaration
(package_declaration
  (scoped_identifier) @package.name) @package

; Annotations
(annotation
  name: (identifier) @annotation.name) @annotation

(marker_annotation
  name: (identifier) @marker_annotation.name) @marker_annotation

(annotation
  name: (identifier) @annotation.name
  arguments: (annotation_argument_list) @annotation.args) @annotation

; Generic class
(class_declaration
  name: (identifier) @generic_class.name
  type_parameters: (type_parameters) @generic_class.type_params) @generic_class

; Generic method
(method_declaration
  type_parameters: (type_parameters) @generic_method.type_params
  name: (identifier) @generic_method.name) @generic_method

; Lambda expression
(lambda_expression
  parameters: (_) @lambda.params
  body: (_) @lambda.body) @lambda

; Method reference
(method_reference
  (identifier) @method_ref.type
  (identifier) @method_ref.method) @method_reference

; Try-catch block
(try_statement
  body: (block) @try.body
  (catch_clause
    (catch_formal_parameter
      (catch_type) @catch.type)
    body: (block) @catch.body)) @try_catch

; Throws declaration
(method_declaration
  (throws
    (type_identifier) @throws.exception)) @method_throws

; Inner class
(class_declaration
  body: (class_body
    (class_declaration
      name: (identifier) @inner_class.name))) @outer_class

; Anonymous class
(object_creation_expression
  type: (type_identifier) @anonymous_class.type
  (class_body) @anonymous_class.body) @anonymous_class
