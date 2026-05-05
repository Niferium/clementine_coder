import mlx.core as mx
from mlx_lm import load, generate
from mlx_lm.sample_utils import make_sampler, make_logits_processors
import json
from typing import Dict, Any, List
import src.prompts.sys_prompt as sys_prompt
import logging

class EvaluationAgent:
    """
    A class that evaluates builder agent responses using Qwen3-Coder-30B model.
    """
    
    def __init__(self):
        """
        Initialize the evaluation agent with Qwen3-Coder-30B model.
        
        Args:
            model_path: Path to the Qwen3-Coder-30B model
            max_tokens: Maximum tokens for generation
        """
        self._loaded_model                 = None
        self._loaded_tokenizer             = None
        self.system_prompt = sys_prompt.SYSTEM_PROMPT_EVALUATION_AGENT()
        
    def evaluate_response(
            self,
            builder_response: str, 
            requirements: str = "",
            _loaded_model: Any = None,
            _loaded_tokenizer: Any = None,
            maxTokens: int = 0
    ) -> Dict[str, Any]:
        """
        Evaluate the builder's response and provide detailed feedback.
        
        Args:
            builder_response: The response from the builder agent
            requirements: Optional requirements to consider during evaluation
            
        Returns:
            Dictionary containing evaluation results and feedback
        """
        # ✅ Use chat template — model knows system vs user context
        conversation = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": f"Evaluate this response by a coding agent:\n{builder_response}"}
        ]
        prompt = _loaded_tokenizer.apply_chat_template(conversation, add_generation_prompt=True)


        #Settings for llm
        sampler = make_sampler(temp=0.6, top_p=0.9)
        logits_processors = make_logits_processors(repetition_penalty=1.3)

        # Generate response using the model
        generated_text = generate(
            _loaded_model, 
            _loaded_tokenizer, 
            prompt, 
            max_tokens=512,
            verbose=True,
            sampler = sampler,
            logits_processors = logits_processors
        )

        # Parse the evaluation results
        evaluation_result = self._parse_evaluation(generated_text)
        
        return evaluation_result
    
    def _parse_evaluation(self, evaluation_text: str) -> Dict[str, Any]:
        """
        Parse the evaluation text into structured data.
        
        Args:
            evaluation_text: Text containing evaluation results
            
        Returns:
            Dictionary with parsed evaluation data
        """
        # Simple parsing logic - in a real implementation, you'd want more robust parsing
        evaluation_data = {
            "overall_score": 0,
            "strengths": [],
            "areas_for_improvement": [],
            "recommendations": [],
            "code_quality_score": 0,
            "functionality_score": 0,
    "documentation_score": 0
        }
        
        # Extract scores and sections
        lines = evaluation_text.split('\n')
        for line in lines:
            if "Overall Score" in line:
                try:
                    score = int(line.split(":")[1].strip())
                    evaluation_data["overall_score"] = score
                except:
                    pass
            elif "Strengths:" in line:
                # Extract strengths from the line
                strength_line = line.split("Strengths:")[1].strip()
                if strength_line.startswith("-"):
                    strengths = strength_line.split("-")[1:]
                    evaluation_data["strengths"] = [s.strip() for s in strengths if s.strip()]
                else:
                    evaluation_data["strengths"] = [strength_line]
            elif "Areas for improvement:" in line:
                # Extract areas for improvement
                improvement_line = line.split("Areas for improvement:")[1].strip()
                if improvement_line.startswith("-"):
                    improvements = improvement_line.split("-")[1:]
                    evaluation_data["areas_for_improvement"] = [i.strip() for i in improvements if i.strip()]
                else:
                    evaluation_data["areas_for_improvement"] = [improvement_line]
            elif "Specific recommendations:" in line:
                recommendation_line = line.split("Specific recommendations:")[1].strip()
                if recommendation_line.startswith("-"):
                    recommendations = recommendation_line.split("-")[1:]
                    evaluation_data["recommendations"] = [r.strip() for r in recommendations if r.strip()]
                else:
                    evaluation_data["recommendations"] = [recommendation_line]
        
        return evaluation_data
    
    # def generate_documentation(self, evaluation_result: Dict[str, Any]) -> str:
    #     """
    #     Generate formatted documentation from evaluation results.
        
    #     Args:
    #         evaluation_result: Dictionary containing evaluation data
            
    #     Returns:
    #         Formatted documentation string
    #     """
    #     doc = f"""
    #     Evaluation Report
    #     =================

    #     Overall Score: {evaluation_result.get('overall_score', 0)/10*100}% 
    #     Score: {evaluation_result.get('overall_score', 0)/10*100}% (out of 100)

    #     Strengths:
    #     {'\n'.join([f"- {strength}" for strength in evaluation_result.get('strengths', [])])}

    #     Areas for Improvement:
    #     {'\n'.'} 
    #     """