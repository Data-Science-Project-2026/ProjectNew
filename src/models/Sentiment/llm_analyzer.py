"""
LLM Module for Psychological State Inference and Sentiment Analysis

This module provides functionality to analyze text using Large Language Models
to infer psychological states, emotions, and perform sentiment analysis.
"""

import torch
from transformers import (
    AutoTokenizer, 
    AutoModelForSequenceClassification,
    pipeline
)
from torch.utils.data import Dataset
from typing import Dict, List, Optional, Union
import warnings

warnings.filterwarnings('ignore')


class TextDataset(Dataset):
    """Simple Dataset for efficient batch processing with Hugging Face pipelines."""
    def __init__(self, texts: List[str]):
        self.texts = texts

    def __len__(self):
        return len(self.texts)

    def __getitem__(self, idx):
        return str(self.texts[idx])


class PsychologicalStateAnalyzer:
    """
    Analyzes text to infer psychological states and emotional content.
    Uses pre-trained transformer models for sentiment analysis and emotion detection.
    """
    
    def __init__(
        self, 
        sentiment_model: str = "uer/roberta-base-finetuned-dianping-chinese",
        emotion_model: Optional[str] = None, # Optional for Chinese, or use a zero-shot classifier
        device: Optional[str] = None
    ):
        """
        Initialize the analyzer with specified models.
        
        Args:
            sentiment_model: HuggingFace model for sentiment analysis. 
                           Defaults to a model fine-tuned on Chinese reviews.
            emotion_model: HuggingFace model for emotion detection.
            device: Device to run models on ('cuda', 'cpu', or None for auto)
        """
        if device is None:
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            self.device = device
            
        print(f"Initializing PsychologicalStateAnalyzer on {self.device}...")
        
        # Initialize sentiment analysis pipeline
        # uer/roberta-base-finetuned-dianping-chinese returns labels like "positive (stars)" or similar binary
        self.sentiment_analyzer = pipeline(
            "sentiment-analysis",
            model=sentiment_model,
            device=0 if self.device == "cuda" else -1
        )
        
        # Initialize emotion detection pipeline
        # For Chinese, dedicated emotion models are less common. 
        # We can use a zero-shot classifier if emotion_model is not provided or use a specific one.
        # For now, we'll make it optional or keep the English one if explicitly requested, 
        # but for this specific request, we might handle emotions differently or assume zero-shot.
        if emotion_model:
            self.emotion_analyzer = pipeline(
                "text-classification",
                model=emotion_model,
                device=0 if self.device == "cuda" else -1,
                top_k=None
            )
        else:
            # Fallback or Zero-shot for emotions in Chinese could be added here
            # For this implementation, we will focus on the sentiment score as requested
            self.emotion_analyzer = None

    def analyze_sentiment(self, text: Union[str, List[str]], batch_size: int = 16) -> Union[Dict, List[Dict]]:
        """
        Analyze sentiment of text(s) and return a 0-1 score.
        
        Args:
            text: Single text string or list of text strings
            batch_size: Batch size for processing list of texts (default: 16)
            
        Returns:
            Dictionary or list of dictionaries with sentiment labels and normalized scores (0.0-1.0)
        """
        # Determine if input is a single string or list
        is_single = isinstance(text, str)
        if is_single:
            dataset = [text]
        else:
            # Use custom Dataset for efficient batching if list
            dataset = TextDataset(text)

        # Call pipeline with batch_size, truncation, and max_length to handle long texts and speed up on GPU
        # Pipeline iterates over the Dataset
        results_iterator = self.sentiment_analyzer(
            dataset, 
            batch_size=batch_size, 
            truncation=True, 
            max_length=512
        )
        
        processed_results = []
        
        for res in results_iterator:
            label = res['label'].lower()
            score = res['score']
            
            # Logic for score normalization
            # uer/roberta-base-finetuned-dianping-chinese uses 'positive' (label 1) and 'negative' (label 0)
            
            final_score = score
            normalized_label = label
            
            if 'positive' in label or label == '1' or 'label_1' in label:
                final_score = score # Already high for positive
                normalized_label = 'positive'
            elif 'negative' in label or label == '0' or 'label_0' in label:
                final_score = 1.0 - score # Invert score for negative to represent "positiveness"
                normalized_label = 'negative'
                
            processed_results.append({
                'label': normalized_label, # internal label
                'score': final_score # 0.0 to 1.0 where 1.0 is very positive
            })
            
        return processed_results[0] if is_single else processed_results
    
    def analyze_emotions(self, text: Union[str, List[str]]) -> Union[List[Dict], List[List[Dict]]]:
        """
        Detect emotions in text(s).
        
        Args:
            text: Single text string or list of text strings
            
        Returns:
            List of emotion predictions
        """
        if not self.emotion_analyzer:
            return [{'label': 'neutral', 'score': 0.0}] # Placeholder if no model
            
        results = self.emotion_analyzer(text)
        return results
    
    def infer_psychological_state(self, text: str) -> Dict:
        """
        Comprehensive psychological state inference from text.
        Combines sentiment and emotion analysis.
        
        Args:
            text: Input text to analyze
            
        Returns:
            Dictionary containing:
                - sentiment_score: Numerical sentiment score (0.0-1.0)
                - sentiment_label: positive/negative
                - emotions: Dictionary of emotion scores (if available)
        """
        # Get sentiment
        sentiment_result = self.analyze_sentiment(text)
        
        # Simplistic return as requested
        return {
            'sentiment_score': sentiment_result['score'],
            'sentiment_label': sentiment_result['label'],
            # keeping structure compatible but highlighting the requested feature
        }
    
    def _interpret_psychological_state(
        self, 
        sentiment: str, 
        dominant_emotion: str,
        emotions: Dict[str, float]
    ) -> str:
        """
        Interpret psychological state from sentiment and emotions.
        
        Args:
            sentiment: Overall sentiment label
            dominant_emotion: Most prominent emotion
            emotions: Dictionary of all emotion scores
            
        Returns:
            Human-readable psychological state description
        """
        # Define state mappings
        if sentiment == "POSITIVE":
            if dominant_emotion in ["joy", "surprise"]:
                return "Excited and positive"
            elif dominant_emotion == "neutral":
                return "Calm and content"
            else:
                return "Generally positive"
        else:  # NEGATIVE
            if dominant_emotion in ["anger", "disgust"]:
                return "Frustrated or upset"
            elif dominant_emotion == "fear":
                return "Anxious or worried"
            elif dominant_emotion == "sadness":
                return "Sad or melancholic"
            else:
                return "Generally negative"
    
    def batch_analyze(self, texts: List[str]) -> List[Dict]:
        """
        Analyze multiple texts efficiently.
        
        Args:
            texts: List of text strings to analyze
            
        Returns:
            List of analysis results for each text
        """
        results = []
        for text in texts:
            results.append(self.infer_psychological_state(text))
        return results


class NarrativeAnalyzer:
    """
    Analyzes narratives to extract themes, topics, and contextual information
    relevant to human-nature interactions.
    """
    
    def __init__(
        self,
        model_name: str = "facebook/bart-large-mnli",
        device: Optional[str] = None
    ):
        """
        Initialize narrative analyzer.
        
        Args:
            model_name: HuggingFace model for zero-shot classification
            device: Device to run model on
        """
        if device is None:
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            self.device = device
            
        print(f"Initializing NarrativeAnalyzer on {self.device}...")
        
        self.classifier = pipeline(
            "zero-shot-classification",
            model=model_name,
            device=0 if self.device == "cuda" else -1
        )
        
        # Define nature-related categories
        self.nature_categories = [
            "forest", "mountain", "ocean", "river", "park",
            "wildlife", "plants", "weather", "landscape", "urban nature"
        ]
        
        self.activity_categories = [
            "hiking", "relaxing", "exploring", "observing",
            "photography", "meditation", "exercise", "social activity"
        ]
    
    def extract_environmental_themes(self, text: str) -> Dict:
        """
        Extract environmental and nature-related themes from narrative.
        
        Args:
            text: Narrative text
            
        Returns:
            Dictionary with environmental themes and scores
        """
        result = self.classifier(text, self.nature_categories)
        
        themes = {}
        for label, score in zip(result['labels'], result['scores']):
            themes[label] = score
            
        return {
            'themes': themes,
            'primary_theme': result['labels'][0],
            'primary_theme_score': result['scores'][0]
        }
    
    def extract_activities(self, text: str) -> Dict:
        """
        Extract activities mentioned in narrative.
        
        Args:
            text: Narrative text
            
        Returns:
            Dictionary with activities and scores
        """
        result = self.classifier(text, self.activity_categories)
        
        activities = {}
        for label, score in zip(result['labels'], result['scores']):
            activities[label] = score
            
        return {
            'activities': activities,
            'primary_activity': result['labels'][0],
            'primary_activity_score': result['scores'][0]
        }
