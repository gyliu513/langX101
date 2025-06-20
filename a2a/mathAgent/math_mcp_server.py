#!/usr/bin/env python3
"""
Math MCP Server - Provides mathematical calculation tools via MCP protocol
"""

import asyncio
import json
import sys
from typing import Any, Dict, List
import sympy as sp
import numpy as np
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, ImageContent, EmbeddedResource


# Initialize the MCP server
server = Server("math-mcp-server")


@server.list_tools()
async def list_tools() -> List[Tool]:
    """List available mathematical tools."""
    return [
        Tool(
            name="calculate_expression",
            description="Evaluate a mathematical expression safely using SymPy",
            inputSchema={
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "Mathematical expression to evaluate (e.g., '2+2', 'sin(pi/4)', 'sqrt(16)')"
                    }
                },
                "required": ["expression"]
            }
        ),
        Tool(
            name="solve_equation",
            description="Solve an algebraic equation using SymPy",
            inputSchema={
                "type": "object",
                "properties": {
                    "equation": {
                        "type": "string",
                        "description": "Equation to solve (e.g., 'x**2 - 4 = 0', '2*x + 5 = 11')"
                    },
                    "variable": {
                        "type": "string",
                        "description": "Variable to solve for (default: 'x')",
                        "default": "x"
                    }
                },
                "required": ["equation"]
            }
        ),
        Tool(
            name="derivative",
            description="Calculate the derivative of a mathematical expression",
            inputSchema={
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "Mathematical expression (e.g., 'x**2 + 3*x + 2', 'sin(x)')"
                    },
                    "variable": {
                        "type": "string",
                        "description": "Variable to differentiate with respect to (default: 'x')",
                        "default": "x"
                    }
                },
                "required": ["expression"]
            }
        ),
        Tool(
            name="integral",
            description="Calculate the integral of a mathematical expression",
            inputSchema={
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "Mathematical expression (e.g., 'x**2', 'sin(x)')"
                    },
                    "variable": {
                        "type": "string",
                        "description": "Variable to integrate with respect to (default: 'x')",
                        "default": "x"
                    }
                },
                "required": ["expression"]
            }
        ),
        Tool(
            name="matrix_operations",
            description="Perform matrix operations using NumPy",
            inputSchema={
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "description": "Operation to perform",
                        "enum": ["multiply", "add", "subtract", "inverse", "determinant", "transpose"]
                    },
                    "matrix_a": {
                        "type": "string",
                        "description": "First matrix as JSON string (e.g., '[[1,2],[3,4]]')"
                    },
                    "matrix_b": {
                        "type": "string",
                        "description": "Second matrix as JSON string (required for binary operations)",
                        "default": ""
                    }
                },
                "required": ["operation", "matrix_a"]
            }
        ),
        Tool(
            name="statistics_calculator",
            description="Calculate statistical measures for a dataset",
            inputSchema={
                "type": "object",
                "properties": {
                    "data": {
                        "type": "string",
                        "description": "List of numbers as JSON string (e.g., '[1,2,3,4,5]')"
                    },
                    "operation": {
                        "type": "string",
                        "description": "Statistical operation to perform",
                        "enum": ["mean", "median", "mode", "std", "var", "min", "max", "sum"]
                    }
                },
                "required": ["data", "operation"]
            }
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle tool calls."""
    
    if name == "calculate_expression":
        return await handle_calculate_expression(arguments)
    elif name == "solve_equation":
        return await handle_solve_equation(arguments)
    elif name == "derivative":
        return await handle_derivative(arguments)
    elif name == "integral":
        return await handle_integral(arguments)
    elif name == "matrix_operations":
        return await handle_matrix_operations(arguments)
    elif name == "statistics_calculator":
        return await handle_statistics_calculator(arguments)
    else:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def handle_calculate_expression(arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle expression calculation."""
    try:
        expression = arguments.get("expression", "")
        if not expression:
            return [TextContent(type="text", text="Error: No expression provided")]
        
        # Use sympy for safe evaluation
        result = sp.sympify(expression)
        
        # Convert to float if it's a number, otherwise keep as symbolic
        if result.is_number:
            result_text = f"Result: {float(result)}"
        else:
            result_text = f"Result: {str(result)}"
        
        return [TextContent(type="text", text=result_text)]
        
    except Exception as e:
        return [TextContent(type="text", text=f"Error calculating expression: {str(e)}")]


async def handle_solve_equation(arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle equation solving."""
    try:
        equation = arguments.get("equation", "")
        variable = arguments.get("variable", "x")
        
        if not equation:
            return [TextContent(type="text", text="Error: No equation provided")]
        
        # Parse the equation
        if "=" in equation:
            left, right = equation.split("=")
            expr = sp.sympify(left.strip()) - sp.sympify(right.strip())
        else:
            expr = sp.sympify(equation)
        
        var = sp.Symbol(variable)
        solutions = sp.solve(expr, var)
        
        if solutions:
            solutions_text = ", ".join(str(sol) for sol in solutions)
            result_text = f"Solutions for {variable}: {solutions_text}"
        else:
            result_text = f"No solutions found for equation: {equation}"
        
        return [TextContent(type="text", text=result_text)]
        
    except Exception as e:
        return [TextContent(type="text", text=f"Error solving equation: {str(e)}")]


async def handle_derivative(arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle derivative calculation."""
    try:
        expression = arguments.get("expression", "")
        variable = arguments.get("variable", "x")
        
        if not expression:
            return [TextContent(type="text", text="Error: No expression provided")]
        
        expr = sp.sympify(expression)
        var = sp.Symbol(variable)
        result = sp.diff(expr, var)
        
        result_text = f"Derivative of {expression} with respect to {variable}: {str(result)}"
        return [TextContent(type="text", text=result_text)]
        
    except Exception as e:
        return [TextContent(type="text", text=f"Error calculating derivative: {str(e)}")]


async def handle_integral(arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle integral calculation."""
    try:
        expression = arguments.get("expression", "")
        variable = arguments.get("variable", "x")
        
        if not expression:
            return [TextContent(type="text", text="Error: No expression provided")]
        
        expr = sp.sympify(expression)
        var = sp.Symbol(variable)
        result = sp.integrate(expr, var)
        
        result_text = f"Integral of {expression} with respect to {variable}: {str(result)}"
        return [TextContent(type="text", text=result_text)]
        
    except Exception as e:
        return [TextContent(type="text", text=f"Error calculating integral: {str(e)}")]


async def handle_matrix_operations(arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle matrix operations."""
    try:
        operation = arguments.get("operation", "")
        matrix_a_str = arguments.get("matrix_a", "")
        matrix_b_str = arguments.get("matrix_b", "")
        
        if not operation or not matrix_a_str:
            return [TextContent(type="text", text="Error: Operation and matrix_a are required")]
        
        # Parse matrices
        import ast
        mat_a = np.array(ast.literal_eval(matrix_a_str))
        
        if operation == "transpose":
            result = mat_a.T
            result_text = f"Transpose result: {result.tolist()}"
        elif operation == "determinant":
            if mat_a.shape[0] != mat_a.shape[1]:
                return [TextContent(type="text", text="Error: Determinant requires a square matrix")]
            result = np.linalg.det(mat_a)
            result_text = f"Determinant: {float(result)}"
        elif operation == "inverse":
            if mat_a.shape[0] != mat_a.shape[1]:
                return [TextContent(type="text", text="Error: Inverse requires a square matrix")]
            result = np.linalg.inv(mat_a)
            result_text = f"Inverse result: {result.tolist()}"
        else:
            # Binary operations
            if not matrix_b_str:
                return [TextContent(type="text", text=f"Error: Operation '{operation}' requires two matrices")]
            
            mat_b = np.array(ast.literal_eval(matrix_b_str))
            
            if operation == "add":
                result = mat_a + mat_b
            elif operation == "subtract":
                result = mat_a - mat_b
            elif operation == "multiply":
                result = np.dot(mat_a, mat_b)
            else:
                return [TextContent(type="text", text=f"Error: Unknown operation: {operation}")]
            
            result_text = f"Matrix {operation} result: {result.tolist()}"
        
        return [TextContent(type="text", text=result_text)]
        
    except Exception as e:
        return [TextContent(type="text", text=f"Error in matrix operation: {str(e)}")]


async def handle_statistics_calculator(arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle statistical calculations."""
    try:
        data_str = arguments.get("data", "")
        operation = arguments.get("operation", "")
        
        if not data_str or not operation:
            return [TextContent(type="text", text="Error: Both data and operation are required")]
        
        import ast
        from statistics import mode, median
        
        numbers = ast.literal_eval(data_str)
        if not isinstance(numbers, list):
            return [TextContent(type="text", text="Error: Data must be a list of numbers")]
        
        arr = np.array(numbers)
        
        if operation == "mean":
            result = float(np.mean(arr))
        elif operation == "median":
            result = float(median(numbers))
        elif operation == "mode":
            result = float(mode(numbers))
        elif operation == "std":
            result = float(np.std(arr))
        elif operation == "var":
            result = float(np.var(arr))
        elif operation == "min":
            result = float(np.min(arr))
        elif operation == "max":
            result = float(np.max(arr))
        elif operation == "sum":
            result = float(np.sum(arr))
        else:
            return [TextContent(type="text", text=f"Error: Unknown statistical operation: {operation}")]
        
        result_text = f"Statistical {operation} of {numbers}: {result}"
        return [TextContent(type="text", text=result_text)]
        
    except Exception as e:
        return [TextContent(type="text", text=f"Error in statistical calculation: {str(e)}")]


async def main():
    """Main entry point for the math MCP server."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main()) 