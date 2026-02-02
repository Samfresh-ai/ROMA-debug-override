; Tree-sitter query patterns for Rust
; Used to extract semantic information from Rust source code

; Function definitions
(function_item
  name: (identifier) @function.name
  parameters: (parameters) @function.params
  return_type: (_)? @function.return_type
  body: (block) @function.body) @function

; Async functions
(function_item
  (function_modifiers
    "async" @async)
  name: (identifier) @async_function.name) @async_function

; Public functions
(function_item
  (visibility_modifier) @visibility
  name: (identifier) @pub_function.name) @pub_function

; Struct definitions
(struct_item
  name: (type_identifier) @struct.name
  body: (field_declaration_list)? @struct.body) @struct

; Tuple struct
(struct_item
  name: (type_identifier) @tuple_struct.name
  body: (ordered_field_declaration_list) @tuple_struct.body) @tuple_struct

; Enum definitions
(enum_item
  name: (type_identifier) @enum.name
  body: (enum_variant_list) @enum.body) @enum

; Enum variant
(enum_variant
  name: (identifier) @enum_variant.name) @enum_variant

; Trait definitions
(trait_item
  name: (type_identifier) @trait.name
  body: (declaration_list) @trait.body) @trait

; Impl blocks
(impl_item
  trait: (type_identifier)? @impl.trait
  type: (type_identifier) @impl.type
  body: (declaration_list) @impl.body) @impl

; Method in impl block
(impl_item
  body: (declaration_list
    (function_item
      name: (identifier) @method.name))) @method

; Associated function (no self)
(impl_item
  body: (declaration_list
    (function_item
      name: (identifier) @associated_fn.name
      parameters: (parameters) @associated_fn.params))) @associated_fn

; Type alias
(type_item
  name: (type_identifier) @type_alias.name
  type: (_) @type_alias.value) @type_alias

; Use declarations (imports)
(use_declaration
  argument: (scoped_identifier) @use.path) @use

(use_declaration
  argument: (identifier) @use.simple) @use

(use_declaration
  argument: (use_wildcard) @use.wildcard) @use

(use_declaration
  argument: (scoped_use_list
    path: (scoped_identifier)? @use.path
    list: (use_list) @use.list)) @use

; Use with alias
(use_declaration
  argument: (use_as_clause
    path: (_) @use.path
    alias: (identifier) @use.alias)) @use

; Module declarations
(mod_item
  name: (identifier) @mod.name
  body: (declaration_list)? @mod.body) @mod

; Const declarations
(const_item
  name: (identifier) @const.name
  type: (_) @const.type
  value: (_) @const.value) @const

; Static declarations
(static_item
  name: (identifier) @static.name
  type: (_) @static.type
  value: (_) @static.value) @static

; Macro definitions
(macro_definition
  name: (identifier) @macro.name) @macro

; Macro invocations
(macro_invocation
  macro: (identifier) @macro_call.name
  (token_tree) @macro_call.args) @macro_call

; Attribute macros (like #[derive])
(attribute_item
  (attribute
    (identifier) @attribute.name)) @attribute

; Derive attribute specifically
(attribute_item
  (attribute
    (identifier) @_derive (#eq? @_derive "derive")
    arguments: (token_tree) @derive.traits)) @derive

; Closure/lambda
(closure_expression
  parameters: (closure_parameters) @closure.params
  body: (_) @closure.body) @closure

; Let bindings
(let_declaration
  pattern: (identifier) @let.name
  type: (_)? @let.type
  value: (_)? @let.value) @let

; Match expression
(match_expression
  value: (_) @match.value
  body: (match_block) @match.arms) @match

; Error handling - Result/Option
(call_expression
  function: (field_expression
    field: (field_identifier) @_method)
  (#match? @_method "^(unwrap|expect|ok|err|map|and_then|or_else)$")) @result_chain
